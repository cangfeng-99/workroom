"""Redact one-time invitation tokens from request and server logs (T017).

Only ``django``/``django.request``/``django.server`` records are filtered, and
only the ``/projects/join/<token>/`` path segment (plain or percent-encoded,
e.g. inside a ``next`` parameter) is replaced. Every other log line and its
status information stays untouched; no logger is disabled.
"""

from __future__ import annotations

import logging
import re

PLACEHOLDER = '/projects/join/<redacted>/'
_PLAIN = re.compile(r"/projects/join/[^/\s\"'<>]+/")
_ENCODED = re.compile(r"(?i)%2fprojects%2fjoin%2f[^&\s\"'<>]+")
LOGGER_NAMES = ('django', 'django.request', 'django.server')


def scrub(text: str) -> str:
    if 'join' not in text.lower():
        return text
    return _ENCODED.sub(PLACEHOLDER, _PLAIN.sub(PLACEHOLDER, text))


class InvitationTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            return True
        cleaned = scrub(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def install() -> None:
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        if not any(isinstance(item, InvitationTokenFilter) for item in logger.filters):
            logger.addFilter(InvitationTokenFilter())
        for handler in logger.handlers:
            if not any(
                isinstance(item, InvitationTokenFilter) for item in handler.filters
            ):
                handler.addFilter(InvitationTokenFilter())
