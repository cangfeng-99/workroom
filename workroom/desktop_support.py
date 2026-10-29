"""Django-free paths and lifecycle lock, shared by desktop and CLI launchers."""

from __future__ import annotations

import json
import os
import re
import stat
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class DesktopError(RuntimeError):
    pass


class InstanceRunning(DesktopError):
    pass


def data_location(environ, home, explicit=None):
    return Path(explicit or (Path(environ.get("LOCALAPPDATA") or home) / "WorkRoom")).absolute()


def application_environment(environ, data):
    result = {key: value for key, value in environ.items() if not key.startswith("WORKROOM_")}
    result.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        WORKROOM_MODE="local",
        WORKROOM_LAUNCH_MODE="local",
        WORKROOM_DEBUG="0",
        WORKROOM_DATA_DIR=str(data),
        WORKROOM_DB_PATH=str(data / "db.sqlite3"),
    )
    return result


def linked(path):
    info = path.lstat()
    return (
        stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & 0x400)
        or (path.is_file() and info.st_nlink > 1)
    )


@contextmanager
def _file_lock(data, name):
    data = Path(data).absolute()
    for ancestor in [data, *data.parents]:
        if ancestor.exists() and linked(ancestor):
            raise DesktopError("应用数据目录不能通过链接访问。")
    data.mkdir(parents=True, exist_ok=True)
    path = data / name
    if path.exists() and linked(path):
        raise DesktopError("启动锁文件不能是链接。")
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise InstanceRunning("同一数据目录的 WorkRoom 已在运行。") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def instance_lock(data):
    with _file_lock(data, ".app-instance.lock"):
        yield


@contextmanager
def operation_lock(data):
    try:
        with _file_lock(data, ".desktop-data.lock"):
            yield
    except InstanceRunning as exc:
        raise DesktopError("应用正在启动、升级或恢复数据，请稍后重试。") from exc


def request_status(record):
    target = record["url"] + "_desktop/" + record["launch_id"] + "/status"
    with urllib.request.urlopen(target, timeout=1) as reply:
        return json.loads(reply.read(4096))


def running_instance(data, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        try:
            path = Path(data) / "desktop-instance.json"
            if linked(path) or path.stat().st_size > 8192:
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                return None
            parsed = urlsplit(str(record.get("url", "")))
            if (
                parsed.scheme != "http"
                or parsed.hostname != "127.0.0.1"
                or not parsed.port
                or parsed.netloc != f"127.0.0.1:{parsed.port}"
                or parsed.path != "/"
                or parsed.query
                or parsed.fragment
                or not re.fullmatch(r"[0-9a-f]{32}", str(record.get("launch_id", "")))
                or not isinstance(record.get("pid"), int)
                or record["pid"] <= 0
            ):
                return None
            status = request_status(record)
            if (
                status.get("application") == "WorkRoom"
                and status.get("launch_id") == record["launch_id"]
                and status.get("pid") == record["pid"]
            ):
                return record
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.1)
