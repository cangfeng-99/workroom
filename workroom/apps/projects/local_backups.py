"""Private local snapshots. Restores run before the web server, never in a request.

Archives are portable data, not trusted instructions. No paths or SQL from an
archive are executed; its schema must match this installation exactly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import connection

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_MEMORY_FILE = 4 * 1024 * 1024
MAX_FILES = 2048
TOKEN_TTL = 86400
FORMAT = "workroom-local-backup"
COUNTS = {
    "projects": "projects_project",
    "tasks": "projects_task",
    "deliveries": "projects_delivery",
    "messages": "projects_chatmessage",
    "library": "projects_libraryentry",
}


class BackupError(ValueError):
    pass


def _local_only():
    if settings.WORKROOM_MODE != "local":
        raise BackupError("此功能仅供本机单人版使用。")


def _linked(path):
    info = path.lstat()
    return (
        stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & 0x400)
        or (path.is_file() and info.st_nlink > 1)
    )


def data_dir():
    _local_only()
    base = Path(settings.DATA_DIR).absolute()
    for item in [base, *base.parents]:
        if item.exists() and _linked(item):
            raise BackupError("应用数据目录不能通过链接访问。")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _folder(name):
    target = data_dir() / name
    target.mkdir(exist_ok=True)
    if _linked(target):
        raise BackupError("备份目录不能是链接。")
    return target


def _remove_owned(path, parent):
    # Both paths are generated here, but verify the absolute boundary on Windows
    # before any recursive removal as well.
    if (
        path.resolve().is_relative_to(parent.resolve())
        and path.resolve() != parent.resolve()
        and not _linked(path)
    ):
        shutil.rmtree(path)
    else:
        raise BackupError("临时目录边界不正确，未删除。")


@contextmanager
def _connect(name, **kwargs):
    db = sqlite3.connect(name, **kwargs)
    try:
        with db:
            yield db
    finally:
        db.close()


def _db():
    name = str(connection.settings_dict["NAME"])
    return _connect(name, uri=name.startswith("file:"), timeout=10)


@contextmanager
def _readonly(path):
    with _connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        yield db


def _schema(db):
    return db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()


def _migrations(db):
    return db.execute("SELECT app,name FROM django_migrations ORDER BY app,name").fetchall()


def _stats(db):
    # Table names come from this fixed mapping, never the uploaded manifest.
    return {
        key: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for key, table in COUNTS.items()
    }


def _safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 500 or "\\" in name:
        raise BackupError("备份内有非法文件路径。")
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name:
        raise BackupError("备份内有非法文件路径。")
    for part in path.parts:
        if (
            part in {".", ".."}
            or any(c in part for c in ':<>"|?*')
            or any(ord(c) < 32 for c in part)
            or part.endswith((" ", "."))
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
        ):
            raise BackupError("备份内有非法文件路径。")
    if name not in {"manifest.json", "database.sqlite3"}:
        if (
            len(path.parts) < 3
            or path.parts[0] != "memories"
            or not re.fullmatch(r"[1-9][0-9]*", path.parts[1])
        ):
            raise BackupError("备份包含未支持的文件。")


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_json(path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _backup_progress(start, status, remaining, total):
    if status != sqlite3.SQLITE_DONE and time.monotonic() - start > 15:
        raise BackupError("数据库仍在忙碌，备份或恢复已取消，请稍后重试。")


def _copy_database(source, dest):
    start = time.monotonic()
    source.backup(
        dest,
        pages=128,
        sleep=0.05,
        progress=lambda status, remaining, total: _backup_progress(start, status, remaining, total),
    )


def export_backup(reason="manual"):
    """Snapshot SQLite first, then copy only explicitly authorised .workroom data."""
    base = _folder("backups")
    target = base / f"workroom-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.zip"
    try:
        with tempfile.TemporaryDirectory(prefix="export-", dir=base) as scratch:
            stage = Path(scratch)
            snapshot = stage / "database.sqlite3"
            with _db() as source, _connect(snapshot) as dest:
                _copy_database(source, dest)
            with _readonly(snapshot) as db:
                counts = _stats(db)
                projects = db.execute(
                    "SELECT id,name,workspace_path,workspace_authorized_at FROM projects_project"
                ).fetchall()
            warnings = []
            files = {"database.sqlite3": snapshot}
            for pk, name, workspace, authorized in projects:
                if not workspace:
                    continue
                root = Path(workspace)
                # Recovered memories already belong to this application even
                # while the original code workspace needs new authorisation.
                recovered_root = data_dir() / "recovered-workspaces"
                recovered_memory = root.resolve().is_relative_to(recovered_root.resolve())
                if not authorized and not recovered_memory:
                    continue
                memory = root / ".workroom"
                if not memory.exists():
                    warnings.append(f"「{name}」没有可备份的 .workroom 记忆。")
                    continue
                # Refuse junctions/symlinks instead of following an authorised
                # folder into an unrelated location.
                for ancestor in [memory, root, *root.parents]:
                    if ancestor.exists() and _linked(ancestor):
                        raise BackupError("工作区记忆含链接，未生成不完整备份。")
                for folder, dirs, names in os.walk(memory, followlinks=False):
                    for leaf in dirs + names:
                        path = Path(folder) / leaf
                        if _linked(path):
                            raise BackupError("工作区记忆含链接，未生成不完整备份。")
                    for leaf in names:
                        path = Path(folder) / leaf
                        rel = f"memories/{pk}/" + path.relative_to(memory).as_posix()
                        _safe_name(rel)
                        before = path.stat()
                        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MEMORY_FILE:
                            raise BackupError("记忆文件过大或不是普通文件，未生成备份。")
                        saved = stage / rel
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, saved)
                        after = path.stat()
                        if (before.st_size, before.st_mtime_ns) != (
                            after.st_size,
                            after.st_mtime_ns,
                        ):
                            raise BackupError("记忆正在改变，请稍后重新备份。")
                        files[rel] = saved
                        if len(files) + 1 > MAX_FILES:
                            raise BackupError("记忆文件数量超出本版限制。")
            if sum(p.stat().st_size for p in files.values()) > MAX_TOTAL:
                raise BackupError("备份数据超出本版 256 MB 限制。")
            manifest = dict(
                format=FORMAT,
                version=1,
                created_at=datetime.now(timezone.utc).isoformat(),
                reason=reason,
                counts=counts,
                warnings=warnings,
                files={
                    name: dict(size=p.stat().st_size, sha256=_digest(p))
                    for name, p in files.items()
                },
            )
            temp = stage / "package.zip"
            with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
                for name, path in files.items():
                    archive.write(path, name)
            if temp.stat().st_size > MAX_ARCHIVE:
                raise BackupError("压缩包超过本版 64 MB 限制。")
            os.replace(temp, target)
        return target
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        raise BackupError("无法生成完整备份，请检查磁盘空间和文件访问权限。") from exc


def _unpack(archive_path, stage):
    if archive_path.stat().st_size > MAX_ARCHIVE:
        raise BackupError("备份 ZIP 超过 64 MB。")
    with zipfile.ZipFile(archive_path) as archive:
        items = archive.infolist()
        names = [item.filename for item in items]
        if len(names) > MAX_FILES or len(set(name.casefold() for name in names)) != len(names):
            raise BackupError("文件重复或数量超出限制。")
        if not {"manifest.json", "database.sqlite3"} <= set(names):
            raise BackupError("缺少 WorkRoom 备份清单或数据库。")
        if sum(item.file_size for item in items) > MAX_TOTAL:
            raise BackupError("解压大小超过 256 MB 限制。")
        for item in items:
            _safe_name(item.filename)
            if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                raise BackupError("备份不能包含链接、目录条目或加密 ZIP。")
            limit = (
                256 * 1024
                if item.filename == "manifest.json"
                else (MAX_TOTAL if item.filename == "database.sqlite3" else MAX_MEMORY_FILE)
            )
            if item.file_size > limit:
                raise BackupError("备份内的单个文件超过限制。")
            saved = stage / item.filename
            saved.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, saved.open("xb") as dest:
                shutil.copyfileobj(source, dest, length=64 * 1024)
        manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != FORMAT
            or manifest.get("version") != 1
        ):
            raise BackupError("不支持此备份格式或版本。")
        file_meta = manifest.get("files")
        if not isinstance(file_meta, dict) or set(file_meta) != set(names) - {"manifest.json"}:
            raise BackupError("备份清单与实际文件不一致。")
        for name, meta in file_meta.items():
            saved = stage / name
            if (
                not isinstance(meta, dict)
                or meta.get("size") != saved.stat().st_size
                or meta.get("sha256") != _digest(saved)
            ):
                raise BackupError("备份文件校验失败，内容可能损坏。")
    with _readonly(stage / "database.sqlite3") as source, _db() as current:
        if (
            source.execute("PRAGMA integrity_check").fetchone() != ("ok",)
            or source.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise BackupError("数据库完整性或关系校验失败。")
        if _schema(source) != _schema(current) or _migrations(source) != _migrations(current):
            raise BackupError("数据库版本或结构不匹配，请使用生成备份时的程序版本。")
        counts = _stats(source)
        project_ids = {str(row[0]) for row in source.execute("SELECT id FROM projects_project")}
    memory_names = [name for name in names if name.startswith("memories/")]
    if any(PurePosixPath(name).parts[1] not in project_ids for name in memory_names):
        raise BackupError("记忆不属于备份中的项目。")
    if counts != manifest.get("counts"):
        raise BackupError("清单中的数量与数据库不一致。")
    # Only fixed types are presented, never arbitrary uploaded manifest values.
    created_at = datetime.fromisoformat(str(manifest.get("created_at", "")))
    if created_at.tzinfo is None:
        raise BackupError("备份时间缺少时区，请选择 WorkRoom 导出的完整备份。")
    warnings = manifest.get("warnings", [])
    if (
        not isinstance(warnings, list)
        or any(not isinstance(x, str) or len(x) > 600 for x in warnings)
        or len(warnings) > 1000
    ):
        raise BackupError("备份提示格式不正确。")
    return dict(
        counts=counts,
        memory_files=len(memory_names),
        created_at=created_at.isoformat(),
        size=archive_path.stat().st_size,
        warnings=warnings,
    )


def _checked_archive(path):
    try:
        with tempfile.TemporaryDirectory(prefix="check-", dir=_folder("backup-imports")) as scratch:
            return _unpack(path, Path(scratch))
    except (
        OSError,
        sqlite3.Error,
        zipfile.BadZipFile,
        RuntimeError,
        UnicodeError,
        ValueError,
    ) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("无法读取有效的 WorkRoom 备份；原数据未更改。") from exc


def inspect_upload(stream):
    token = uuid.uuid4().hex
    folder = _folder("backup-imports")
    pending = restore_state().get("pending", {}).get("token")
    existing = [
        p for p in folder.glob("*.zip") if re.fullmatch(r"[0-9a-f]{32}", p.stem) and not _linked(p)
    ]
    for old in existing:
        if (
            old.stem != pending
            and not _linked(old)
            and time.time() - old.stat().st_mtime > TOKEN_TTL
        ):
            old.unlink()
    remaining = sorted((p for p in existing if p.exists()), key=lambda p: p.stat().st_mtime)
    while len(remaining) >= 8:
        old = next((p for p in remaining if p.stem != pending), None)
        if old is None:
            raise BackupError("待恢复的备份正在使用，请先完成或取消恢复。")
        old.unlink()
        remaining.remove(old)
    target = folder / (token + ".zip")
    try:
        with target.open("xb") as dest:
            total = 0
            while block := stream.read(64 * 1024):
                total += len(block)
                if total > MAX_ARCHIVE:
                    raise BackupError("备份 ZIP 超过 64 MB。")
                dest.write(block)
        summary = _checked_archive(target)
        summary["token"] = token
        return summary
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _import_path(token):
    if not re.fullmatch(r"[0-9a-f]{32}", str(token)):
        raise BackupError("备份检查记录无效，请重新选择文件。")
    path = _folder("backup-imports") / (token + ".zip")
    if not path.is_file() or _linked(path):
        raise BackupError("备份检查记录不存在，请重新选择文件。")
    if time.time() - path.stat().st_mtime > TOKEN_TTL:
        raise BackupError("备份检查已过期，请重新选择文件。")
    return path


def preview(token):
    summary = _checked_archive(_import_path(token))
    return dict(summary, token=token)


def _ensure_idle():
    from .models import ReplyJob, TaskClaim
    from .queue import worker_online

    if worker_online():
        raise BackupError("仍有近期 Worker 心跳；请先停止 Worker，等心跳过期后再恢复。")
    if ReplyJob.objects.filter(status__in=["queued", "running"]).exists():
        raise BackupError("仍有排队或执行中的 AI 任务，请处理后再恢复。")
    from django.utils import timezone as django_timezone

    if TaskClaim.objects.filter(status="active", expires_at__gt=django_timezone.now()).exists():
        raise BackupError("仍有有效的工具任务认领，请让执行者先交付或释放后再恢复。")


def schedule_restore(token):
    _ensure_idle()
    summary = preview(token)
    _write_json(
        data_dir() / "pending-restore.json",
        dict(
            token=token,
            sha256=_digest(_import_path(token)),
            scheduled_at=datetime.now(timezone.utc).isoformat(),
        ),
    )
    return summary


def cancel_restore():
    (data_dir() / "pending-restore.json").unlink(missing_ok=True)


def restore_state():
    result = {"has_pending": (data_dir() / "pending-restore.json").exists()}
    for name, key in [("pending-restore.json", "pending"), ("restore-result.json", "result")]:
        path = data_dir() / name
        if path.is_file() and not _linked(path):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    if key == "pending" and not re.fullmatch(
                        r"[0-9a-f]{32}", str(value.get("token", ""))
                    ):
                        raise ValueError("invalid restore record")
                    result[key] = value
            except (ValueError, OSError):
                result["error"] = "恢复记录损坏，请取消计划后重新检查备份。"
    return result


def _replace_database(source_path):
    # SQLite backup commits the destination in one transaction. An exception
    # rolls it back; never replace a live DB file or detach its WAL sidecars.
    connection.close()
    with _readonly(source_path) as source, _db() as dest:
        _copy_database(source, dest)
    connection.close()


def apply_pending_restore():
    """Launcher only: call inside instance_lock, before migrate/runserver."""
    pending_path = data_dir() / "pending-restore.json"
    if not pending_path.exists():
        return None
    result = dict(
        status="interrupted",
        message="恢复过程未正常结束，请核对项目数据和恢复前备份，再决定是否重新恢复。",
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    recovered = None
    committed = False
    attempt_path = data_dir() / "restore-in-progress.json"
    try:
        if _linked(pending_path):
            raise BackupError("恢复计划不能是链接。")
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        if not isinstance(pending, dict):
            raise BackupError("恢复计划无效，请重新检查备份。")
        # Consume before changing any data. A crash must not silently replay.
        os.replace(pending_path, attempt_path)
        _write_json(data_dir() / "restore-result.json", result)
        archive = _import_path(pending.get("token"))
        if _digest(archive) != pending.get("sha256"):
            raise BackupError("检查后的备份已经改变，请重新检查。")
        _ensure_idle()
        with tempfile.TemporaryDirectory(
            prefix="restore-", dir=_folder("backup-imports")
        ) as scratch:
            stage = Path(scratch)
            summary = _unpack(archive, stage)
            safety = export_backup(reason="before-restore")
            result["safety_backup"] = str(safety)
            _write_json(data_dir() / "restore-result.json", result)
            recovered_base = _folder("recovered-workspaces")
            recovered = Path(tempfile.mkdtemp(prefix="restore-", dir=recovered_base))
            with _connect(stage / "database.sqlite3") as db:
                for (pk,) in db.execute("SELECT id FROM projects_project").fetchall():
                    memory = stage / f"memories/{pk}"
                    new_root = recovered / str(pk)
                    new_root.mkdir()
                    if memory.exists():
                        shutil.copytree(memory, new_root / ".workroom")
                    db.execute(
                        "UPDATE projects_project SET workspace_path=?,workspace_authorized_at=NULL WHERE id=?",
                        (str(new_root), pk),
                    )
                now = datetime.now(timezone.utc).isoformat()
                db.execute("DELETE FROM django_session")
                db.execute("UPDATE projects_tooltoken SET revoked_at=?", (now,))
                db.execute("UPDATE projects_invitation SET revoked_at=?", (now,))
                db.execute("UPDATE projects_taskclaim SET status='released' WHERE status='active'")
                db.execute(
                    "UPDATE projects_replyjob SET status='cancelled',error='恢复后已停止，请核对后手工重试' WHERE status IN ('queued','running')"
                )
                db.execute("DELETE FROM projects_workerheartbeat")
            _replace_database(stage / "database.sqlite3")
            committed = True
            result.update(
                status="success",
                message="恢复完成。项目和记忆已恢复；请重新关联代码工作区，并重新连接外部工具。",
                counts=summary["counts"],
            )
    except (
        BackupError,
        OSError,
        sqlite3.Error,
        ValueError,
        zipfile.BadZipFile,
        RuntimeError,
    ) as exc:
        if committed:
            result.update(
                status="success",
                message="数据库已恢复，但临时文件清理失败。请核对项目和恢复前备份。",
            )
        else:
            result["status"] = "error"
            result["message"] = (
                str(exc)
                if isinstance(exc, BackupError)
                else "恢复失败，原数据库保留。请检查磁盘空间和备份版本后重新检查。"
            )
        if recovered is not None and not committed:
            try:
                _remove_owned(recovered, _folder("recovered-workspaces"))
            except OSError:
                result["message"] += " 临时记忆目录未清理，请保留恢复前备份后检查磁盘。"
    finally:
        # One explicit confirmation permits one attempt. Never replay silently.
        pending_path.unlink(missing_ok=True)
        _write_json(data_dir() / "restore-result.json", result)
        attempt_path.unlink(missing_ok=True)
    return result


@contextmanager
def instance_lock():
    """Share the OS lifetime lock with the frozen desktop launcher."""
    from desktop_support import DesktopError
    from desktop_support import instance_lock as desktop_lock

    try:
        with desktop_lock(data_dir()):
            yield
    except DesktopError as exc:
        raise BackupError(str(exc)) from exc


def backup_before_migrate():
    from django.db.migrations.executor import MigrationExecutor

    with _db() as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects_project'"
        ).fetchone():
            return None
        if db.execute("SELECT count(*) FROM projects_project").fetchone()[0] == 0:
            return None
    executor = MigrationExecutor(connection)
    if not executor.migration_plan(executor.loader.graph.leaf_nodes()):
        return None
    _ensure_idle()
    return export_backup(reason="before-upgrade")
