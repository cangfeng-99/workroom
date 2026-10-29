"""Template context shared by all pages."""

from __future__ import annotations

from django.conf import settings


def workroom_context(request):
    return {
        'workroom_mode': getattr(settings, 'WORKROOM_MODE', 'local'),
        'workroom_is_server': getattr(settings, 'WORKROOM_MODE', 'local') == 'server',
        'allow_registration': getattr(settings, 'WORKROOM_ALLOW_REGISTRATION', False),
        'local_preview': getattr(settings, 'WORKROOM_LOCAL_PREVIEW', False),
    }
