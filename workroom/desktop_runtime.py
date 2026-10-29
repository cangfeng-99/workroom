"""Local desktop service with a real start/stop lifecycle."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import desktop_support as support


class DesktopServer:
    host = "127.0.0.1"

    def __init__(self, application, static_root):
        from waitress import create_server
        from whitenoise import WhiteNoise

        self.launch_id = uuid.uuid4().hex
        self.application = WhiteNoise(
            application, root=str(static_root), prefix="static/", max_age=0
        )
        self.server = create_server(
            self._application,
            host=self.host,
            port=0,
            threads=6,
            asyncore_loop_timeout=0.1,
            max_request_body_size=65 * 1024 * 1024,
        )
        self.url = f"http://{self.host}:{self.server.effective_port}/"
        self.thread = threading.Thread(target=self.server.run, name="WorkRoom-web", daemon=True)

    def _application(self, environ, start_response):
        if environ.get("PATH_INFO") == f"/_desktop/{self.launch_id}/status":
            body = json.dumps(
                dict(application="WorkRoom", launch_id=self.launch_id, pid=os.getpid())
            ).encode()
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "no-store"),
                ],
            )
            return [body]
        return self.application(environ, start_response)

    def start(self):
        self.thread.start()

    def stop(self):
        from waitress import wasyncore

        self.server.task_dispatcher.shutdown(cancel_pending=True, timeout=5)
        wasyncore.close_all(self.server._map)
        if self.thread.is_alive():
            self.thread.join(timeout=3)


def write_instance(data, server):
    record = dict(url=server.url, launch_id=server.launch_id, pid=os.getpid())
    target = data / "desktop-instance.json"
    temp = target.with_suffix("." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(temp, target)


def clear_instance(data, server):
    target = data / "desktop-instance.json"
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
        if record.get("launch_id") == server.launch_id:
            target.unlink()
    except (OSError, ValueError, AttributeError):
        logging.getLogger(__name__).warning("Could not clear stale instance metadata")


def open_workbench(url):
    # PyInstaller's DLL search path must not leak into external browser launches.
    frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
    if frozen_windows:
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return webbrowser.open(url)
    finally:
        if frozen_windows:
            ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))


class LogStream:
    encoding = "utf-8"

    def write(self, message):
        if message.strip():
            logging.getLogger("desktop.console").info(message.rstrip())
        return len(message)

    def flush(self):
        pass

    def isatty(self):
        return False


def configure_logs(data):
    logs = data / "logs"
    logs.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs / "desktop.log", maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler],
        force=True,
    )
    if sys.stdout is None:
        sys.stdout = LogStream()
    if sys.stderr is None:
        sys.stderr = LogStream()


def start_application(data):
    import django

    with support.operation_lock(data):
        django.setup()
        from django.conf import settings
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.db import connections

        from apps.projects import local_backups

        local_backups.apply_pending_restore()
        local_backups.backup_before_migrate()
        call_command("migrate", interactive=False, verbosity=0)
    settings.STATIC_ROOT.mkdir(parents=True, exist_ok=True)
    server = DesktopServer(get_wsgi_application(), settings.BUNDLE_DIR / "static")
    connections.close_all()
    try:
        server.start()
        write_instance(data, server)
        return server
    except Exception:
        server.stop()
        raise


def _restart_command(args):
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve().parents[1] / "tools/desktop_entry.py"))
    command.extend(["--data-dir", str(args.data_dir)])
    if args.no_browser:
        command.append("--no-browser")
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description="WorkRoom personal desktop")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--no-ui", action="store_true", help="Diagnostic mode without a control window"
    )
    parser.add_argument(
        "--stop-after", type=float, default=0, help="Diagnostic lifetime in seconds"
    )
    args = parser.parse_args(argv)
    if args.stop_after < 0 or args.stop_after > 600:
        parser.error("--stop-after must be between 0 and 600")
    args.data_dir = support.data_location(os.environ, Path.home(), args.data_dir)
    environment = support.application_environment(os.environ, args.data_dir)
    for key in list(os.environ):
        if key.startswith("WORKROOM_"):
            os.environ.pop(key)
    os.environ.update(environment)
    restart = False
    server = None
    try:
        with support.instance_lock(args.data_dir):
            configure_logs(args.data_dir)
            if args.no_ui:
                server = start_application(args.data_dir)
                if not args.no_browser:
                    open_workbench(server.url)
                try:
                    deadline = time.monotonic() + args.stop_after if args.stop_after else None
                    while deadline is None or time.monotonic() < deadline:
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    pass
                finally:
                    server.stop()
                    clear_instance(args.data_dir, server)
            else:
                from desktop_window import DesktopWindow

                window = DesktopWindow(args.data_dir, no_browser=args.no_browser)
                restart = window.run(lambda: start_application(args.data_dir))
    except support.InstanceRunning:
        existing = support.running_instance(args.data_dir)
        if existing:
            if not args.no_browser:
                open_workbench(existing["url"])
            return 0
        if not args.no_ui:
            _show_error("应用正在启动或关闭，请稍等后再打开。")
        return 2
    except Exception:
        logging.getLogger(__name__).exception("Desktop startup failed")
        if not args.no_ui:
            _show_error("启动未完成。请检查数据目录和 logs/desktop.log 后重试。")
        return 1
    if restart:
        subprocess.Popen(
            _restart_command(args), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    return 0


def _show_error(message):
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "WorkRoom", 0x10)
