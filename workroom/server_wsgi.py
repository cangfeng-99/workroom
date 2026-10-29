"""Public entrypoint never falls back to anonymous desktop mode."""
import os

if os.environ.get('WORKROOM_MODE') != 'server':
    raise RuntimeError('生产入口要求 WORKROOM_MODE=server。')
if os.environ.get('DJANGO_SETTINGS_MODULE', 'config.settings') != 'config.settings':
    raise RuntimeError('生产入口必须使用 config.settings。')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
