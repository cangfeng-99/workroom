"""WorkRoom desktop launcher: migrate, serve, open the browser.

This is the entry point an installer/exe would wrap.
Usage:
    python tools/run_workroom.py [--port 8020] [--no-browser]
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'workroom'
sys.path.insert(0, str(APP))
os.chdir(APP)
os.environ['WORKROOM_MODE'] = os.environ.get('WORKROOM_LAUNCH_MODE', 'local')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('WORKROOM_DATA_DIR', str(APP / 'data'))


def free_port(preferred: int = 0) -> int:
    if preferred:
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _serve(port: int) -> None:
    """多线程 WSGI 服务；没有 waitress 时退回 Django 自带的 runserver。"""
    try:
        from config.wsgi import application
        from waitress import serve
    except (ImportError, ModuleNotFoundError):
        from django.core.management import call_command

        call_command('runserver', f'127.0.0.1:{port}', use_reloader=False, verbosity=1)
        return
    serve(
        application,
        host='127.0.0.1',
        port=port,
        threads=8,
        channel_timeout=120,
        ident='WorkRoom',
    )


def wait_ready(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except Exception:  # noqa: BLE001 - server may not be up yet
            time.sleep(0.4)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    import django

    django.setup()
    from apps.projects import local_backups
    from django.core.management import call_command

    local = os.environ['WORKROOM_MODE'] == 'local'
    try:
        with local_backups.instance_lock() if local else nullcontext():
            if local:
                result = local_backups.apply_pending_restore()
                if result:
                    print(result['message'])
                saved = local_backups.backup_before_migrate()
                if saved:
                    print(f'Before-upgrade backup: {saved}')
            call_command('migrate', interactive=False, verbosity=0)

            port = free_port(args.port)
            url = f'http://127.0.0.1:{port}/'

            if not args.no_browser:
                def open_later() -> None:
                    if wait_ready(url):
                        webbrowser.open(url)

                threading.Thread(target=open_later, daemon=True).start()

            print(f'WorkRoom: {url}')
            _serve(port)
    except local_backups.BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
