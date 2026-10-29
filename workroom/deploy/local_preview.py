"""Run an isolated, loopback-only multi-user preview. Never use for deployment."""

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
DATA = APP / 'data' / 'local-preview'


def prepare_environment(port):
    DATA.mkdir(parents=True, exist_ok=True)
    private = DATA / '.preview-secrets.json'
    if not private.exists():
        with private.open('x', encoding='utf-8') as handle:
            json.dump({
                'secret': secrets.token_urlsafe(64),
                'encryption': base64.urlsafe_b64encode(os.urandom(32)).decode(),
            }, handle)
        private.chmod(0o600)
    values = json.loads(private.read_text(encoding='utf-8'))
    os.environ.update(
        WORKROOM_MODE='server', WORKROOM_DATA_DIR=str(DATA),
        WORKROOM_DB_PATH=str(DATA / 'db.sqlite3'),
        WORKROOM_ALLOWED_HOSTS='127.0.0.1,localhost',
        WORKROOM_PUBLIC_ORIGIN=f'https://127.0.0.1:{port}',
        WORKROOM_SECRET_KEY=values['secret'], WORKROOM_ENCRYPTION_KEY=values['encryption'],
        WORKROOM_ALLOW_REGISTRATION='1', WORKROOM_TRUST_PROXY='0',
        DJANGO_SETTINGS_MODULE='config.settings', PYTHONIOENCODING='utf-8',
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8011)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口必须在 1024..65535 范围内。')
    prepare_environment(args.port)
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    if args.worker:
        call_command('workroom_worker', worker_id='local-preview')
        return
    call_command('migrate', interactive=False)
    call_command('collectstatic', interactive=False, verbosity=0)
    # These overrides apply only to this explicit preview, always bound to loopback.
    # Public server_wsgi/Compose keep the strict HTTPS and secure-cookie settings.
    settings.SECURE_SSL_REDIRECT = False
    settings.SESSION_COOKIE_SECURE = False
    settings.CSRF_COOKIE_SECURE = False
    settings.SECURE_HSTS_SECONDS = 0
    settings.SESSION_COOKIE_NAME = 'workroom_preview_session'
    settings.CSRF_COOKIE_NAME = 'workroom_preview_csrftoken'
    settings.CSRF_TRUSTED_ORIGINS = [f'http://127.0.0.1:{args.port}']
    settings.WORKROOM_LOCAL_PREVIEW = True
    client_homes = DATA / 'client-config-homes.json'
    if client_homes.exists():
        # Explicit, local-owner configuration only; never follows a junction implicitly.
        settings.WORKROOM_CLIENT_CONFIG_HOMES = json.loads(client_homes.read_text(encoding='utf-8'))
    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    worker = None
    with (DATA / 'worker.log').open('a', encoding='utf-8') as log:
        try:
            worker = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--worker', '--port', str(args.port)],
                stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            print(f'本机多人版预览：http://127.0.0.1:{args.port}/register/；独立数据，未部署云端。', flush=True)
            serve(get_wsgi_application(), host='127.0.0.1', port=args.port, threads=2)
        finally:
            if worker is not None:
                worker.terminate()
                worker.wait(timeout=10)


if __name__ == '__main__':
    main()
