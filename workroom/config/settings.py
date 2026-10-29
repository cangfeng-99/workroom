"""Django settings for WorkRoom.

Two explicit modes:

* ``local`` (default) keeps the existing single-user desktop workflow and its
  anonymous local pages, DPAPI key storage and daemon-thread jobs.
* ``server`` is the multi-user deployment: real accounts, project roles,
  database queue/worker, Fernet key storage and strict production settings.

Server mode fails closed: missing or unsafe configuration raises
``ImproperlyConfigured`` instead of silently falling back to local behaviour.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

MODE = (os.environ.get('WORKROOM_MODE') or 'local').strip().lower()
if MODE not in {'local', 'server'}:
    raise ImproperlyConfigured('WORKROOM_MODE 只能是 local 或 server。')
IS_SERVER = MODE == 'server'
WORKROOM_MODE = MODE

# Packaged builds read templates/static from the bundle and keep data in %LOCALAPPDATA%.
FROZEN = getattr(sys, 'frozen', False)
BUNDLE_DIR = Path(getattr(sys, '_MEIPASS', BASE_DIR)) if FROZEN else BASE_DIR
if FROZEN:
    DATA_DIR = Path(os.environ.get('WORKROOM_DATA_DIR') or (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'WorkRoom')).resolve()
elif os.environ.get('WORKROOM_DATA_DIR'):
    DATA_DIR = Path(os.environ['WORKROOM_DATA_DIR']).resolve()
elif IS_SERVER:
    DATA_DIR = BASE_DIR / 'data'
else:
    DATA_DIR = BASE_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Read-only root the local project agent may inspect. Override with WORKROOM_AGENT_ROOT.
AGENT_ROOT = os.environ.get(
    'WORKROOM_AGENT_ROOT',
    str(Path.home() / 'Documents' if FROZEN else BASE_DIR.parent),
)

# Where MCP client configs live (Cursor / Codex / WorkBuddy). Tests override this.
MCP_HOME = Path(os.environ.get('WORKROOM_MCP_HOME') or Path.home())


def _secret_key() -> str:
    """Keep a per-machine key next to the project; never commit it (local mode)."""
    path = DATA_DIR / '.secret_key'
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50), encoding='utf-8')
    return path.read_text(encoding='utf-8').strip()


def _split_env(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]


def validate_server_settings(environ: dict | None = None) -> list[str]:
    """Return configuration errors for server mode; empty means valid.

    Kept pure so tests and the ``workroom_check_server`` command can validate
    a production environment without importing a half-configured settings
    module.
    """
    env = os.environ if environ is None else environ
    errors: list[str] = []

    secret = (env.get('WORKROOM_SECRET_KEY') or '').strip()
    if len(secret) < 50 or len(set(secret)) < 5:
        errors.append('WORKROOM_SECRET_KEY 必须由环境提供，至少 50 字符且不能是重复字符。')
    if secret.lower().startswith(('django-insecure', 'change-me', 'dev-', 'replace', 'example')):
        errors.append('WORKROOM_SECRET_KEY 不能使用示例或开发默认值。')

    hosts = [item.strip() for item in env.get('WORKROOM_ALLOWED_HOSTS', '').split(',') if item.strip()]
    if not hosts:
        errors.append('WORKROOM_ALLOWED_HOSTS 必须显式配置域名。')
    elif '*' in hosts:
        errors.append('WORKROOM_ALLOWED_HOSTS 不允许 *。')

    origin = (env.get('WORKROOM_PUBLIC_ORIGIN') or '').strip()
    if not origin.startswith('https://'):
        errors.append('WORKROOM_PUBLIC_ORIGIN 必须是 https:// 来源。')
    else:
        host = origin[len('https://'):].split('/', 1)[0].split(':', 1)[0]
        if hosts and host not in hosts:
            errors.append('WORKROOM_PUBLIC_ORIGIN 的主机必须在 WORKROOM_ALLOWED_HOSTS 中。')

    if (env.get('WORKROOM_DEBUG') or '0') == '1':
        errors.append('server 模式必须关闭 WORKROOM_DEBUG。')

    encryption_key = (env.get('WORKROOM_ENCRYPTION_KEY') or '').strip()
    if not encryption_key:
        errors.append('server 模式必须提供 WORKROOM_ENCRYPTION_KEY。')
    else:
        try:
            from cryptography.fernet import Fernet

            Fernet(encryption_key.encode('ascii'))
        except Exception:  # noqa: BLE001 - any parse failure is a config error
            errors.append('WORKROOM_ENCRYPTION_KEY 不是有效的 Fernet key。')

    if (env.get('WORKROOM_TRUST_PROXY') or '0') == '1':
        trusted = [item for item in env.get('WORKROOM_TRUSTED_PROXY_IPS', '').split(',') if item.strip()]
        if not trusted:
            errors.append('启用 WORKROOM_TRUST_PROXY 时必须配置 WORKROOM_TRUSTED_PROXY_IPS。')

    return errors


if IS_SERVER:
    SECURE_SSL_REDIRECT = True
    _errors = validate_server_settings()
    if _errors:
        raise ImproperlyConfigured('server 配置无效：' + '；'.join(_errors))

SECRET_KEY = os.environ.get('WORKROOM_SECRET_KEY') or _secret_key()
DEBUG = False if IS_SERVER else os.environ.get('WORKROOM_DEBUG', '1') == '1'

if IS_SERVER:
    ALLOWED_HOSTS = _split_env('WORKROOM_ALLOWED_HOSTS')
else:
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.projects',
]

MIDDLEWARE = [
    'apps.projects.middleware.TrustedProxyMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.projects.middleware.ServerAccessMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BUNDLE_DIR / 'templates'],
        'APP_DIRS': False,  # loaders 里已包含 app_directories
        'OPTIONS': {
            # 开发态也缓存模板：DEBUG 下默认不缓存，每次渲染要 stat 上百个文件，
            # 单次请求多花 100ms 以上。改模板后重启服务即可（waitress 本来不热重载）。
            'loaders': [(
                'django.template.loaders.cached.Loader',
                [
                    'django.template.loaders.filesystem.Loader',
                    'django.template.loaders.app_directories.Loader',
                ],
            )],
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.projects.context.workroom_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASE_NAME = Path(
    os.environ.get('WORKROOM_DB_PATH') or (DATA_DIR / 'db.sqlite3')
).resolve()
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATABASE_NAME,
        # Both modes publish from background threads; reserve a writer before
        # reading inside a short atomic block to avoid SQLite lock upgrades.
        'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BUNDLE_DIR / 'static']
STATIC_ROOT = DATA_DIR / 'staticfiles'
# WhiteNoise：开发态直接读源目录，省掉 collectstatic；
# 生产态长缓存（模板里的 ?v= 版本号负责失效）。
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_AUTOREFRESH = False  # 每次请求 stat 静态文件很贵；改文件后重启一次即可
WHITENOISE_MAX_AGE = 60 if DEBUG else 60 * 60 * 24 * 7
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': ('whitenoise.storage.CompressedManifestStaticFilesStorage'
                    if IS_SERVER else 'whitenoise.storage.CompressedStaticFilesStorage'),
    },
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
SESSION_COOKIE_NAME = 'workroom_session'
CSRF_COOKIE_NAME = 'workroom_csrftoken'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

WORKROOM_ALLOW_REGISTRATION = (
    (os.environ.get('WORKROOM_ALLOW_REGISTRATION') or ('0' if IS_SERVER else '1')) == '1'
)
WORKROOM_ENCRYPTION_KEY = (os.environ.get('WORKROOM_ENCRYPTION_KEY') or '').strip()
WORKROOM_INVITE_TTL_HOURS = int(os.environ.get('WORKROOM_INVITE_TTL_HOURS') or '72')
WORKROOM_JOB_LEASE_SECONDS = int(os.environ.get('WORKROOM_JOB_LEASE_SECONDS') or '600')
WORKROOM_CLAIM_TTL_SECONDS = int(os.environ.get('WORKROOM_CLAIM_TTL_SECONDS') or '1800')
WORKROOM_ALLOW_PUBLIC_DEMO = os.environ.get('WORKROOM_ALLOW_PUBLIC_DEMO') == '1'
WORKROOM_SERVER_URL = (os.environ.get('WORKROOM_SERVER_URL') or '').strip()
WORKROOM_TRUSTED_PROXY_IPS = _split_env('WORKROOM_TRUSTED_PROXY_IPS')
DATA_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024

if IS_SERVER:
    SECURE_REDIRECT_EXEMPT = [r'^healthz$']
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    SECURE_HSTS_SECONDS = int(os.environ.get('WORKROOM_HSTS_SECONDS') or '31536000')
    SECURE_HSTS_INCLUDE_SUBDOMAINS = (
        os.environ.get('WORKROOM_HSTS_INCLUDE_SUBDOMAINS') == '1'
    )
    SECURE_HSTS_PRELOAD = False
    X_FRAME_OPTIONS = 'DENY'
    SESSION_EXPIRE_AT_BROWSER_CLOSE = False
    SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
    CSRF_TRUSTED_ORIGINS = _split_env('WORKROOM_CSRF_TRUSTED_ORIGINS')
    origin = (os.environ.get('WORKROOM_PUBLIC_ORIGIN') or '').strip()
    if origin and origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)
    if (os.environ.get('WORKROOM_TRUST_PROXY') or '0') == '1':
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
        USE_X_FORWARDED_HOST = True
