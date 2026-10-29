"""Shared database limits; raw addresses and passwords are never persisted."""

import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import AuthThrottle


def allow_attempt(request, action, username=""):
    now = timezone.now()
    address = request.META.get("REMOTE_ADDR", "")
    with transaction.atomic():
        AuthThrottle.objects.filter(started_at__lt=now - timedelta(days=1)).delete()
        keys = [(f"{action}|{address}", 30), (f"{action}|{address}|{username.lower()[:150]}", 10)]
        for raw, limit in keys:
            row, _ = AuthThrottle.objects.get_or_create(
                bucket=hashlib.sha256(raw.encode()).hexdigest(), defaults={"started_at": now}
            )
            if row.started_at < now - timedelta(minutes=15):
                row.attempts, row.started_at = 0, now
            if row.attempts >= limit:
                return False
            row.attempts += 1
            row.save(update_fields=["attempts", "started_at"])
    return True
