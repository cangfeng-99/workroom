"""Signed one-time project invitations (T017).

Only the UUID is stored; the shareable URL is rebuilt from a fixed-salt
signature. Expiry, revocation and use are always read from the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from projects.models import ProjectInvitation, ProjectMember

SALT = 'projects.invite.v1'
MAX_TOKEN_LENGTH = 512

VALID = 'valid'
REVOKED = 'revoked'
USED = 'used'
EXPIRED = 'expired'

STATE_LABELS = {
    VALID: '有效',
    REVOKED: '已撤销',
    USED: '已使用',
    EXPIRED: '已过期',
}

JOINED = 'joined'
ALREADY_MEMBER = 'already_member'
UNAVAILABLE = 'unavailable'


def _signer() -> signing.Signer:
    return signing.Signer(salt=SALT)


def build_token(invitation: ProjectInvitation) -> str:
    return _signer().sign_object({'id': str(invitation.pk)})


def parse_token(token: str) -> ProjectInvitation | None:
    """Return the invitation for a signed token, or ``None`` if it is invalid."""
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    try:
        payload = _signer().unsign_object(token)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if not isinstance(payload, dict) or set(payload) != {'id'}:
        return None
    raw = payload['id']
    if not isinstance(raw, str):
        return None
    try:
        pk = uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None
    return ProjectInvitation.objects.select_related('project').filter(pk=pk).first()


def build_url(request, invitation: ProjectInvitation) -> str:
    token = build_token(invitation)
    return request.build_absolute_uri(
        reverse('projects:invitation_join', args=[token])
    )


def state(invitation: ProjectInvitation, now: datetime | None = None) -> str:
    now = now or timezone.now()
    if invitation.used_at is not None:
        return USED
    if invitation.revoked_at is not None:
        return REVOKED
    if invitation.expires_at <= now:
        return EXPIRED
    return VALID


def consume(invitation: ProjectInvitation, user, now: datetime | None = None):
    """Atomically consume a valid invitation and add the human member.

    Returns ``(result, member)``. The conditional update is the only way a
    link can be consumed; if it does not match, nothing is written.
    """
    now = now or timezone.now()
    members = ProjectMember.objects
    with transaction.atomic():
        existing = members.filter(
            project_id=invitation.project_id,
            kind=ProjectMember.Kind.HUMAN,
            user=user,
        ).first()
        if existing is not None:
            return ALREADY_MEMBER, existing
        consumed = ProjectInvitation.objects.filter(
            pk=invitation.pk,
            used_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).update(used_at=now, used_by=user)
        if not consumed:
            current = ProjectInvitation.objects.filter(pk=invitation.pk).first()
            if current is not None and current.used_by_id == user.pk:
                return ALREADY_MEMBER, members.filter(
                    project_id=invitation.project_id,
                    kind=ProjectMember.Kind.HUMAN,
                    user=user,
                ).first()
            return UNAVAILABLE, None
        member, _created = members.get_or_create(
            project_id=invitation.project_id,
            user=user,
            defaults={
                'kind': ProjectMember.Kind.HUMAN,
                'name': user.username,
                'role': invitation.role,
            },
        )
        return JOINED, member
