"""Account, invitation and project-team views (server mode)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .auth_limits import allow_attempt
from .models import (
    Invitation,
    Member,
    ProjectMembership,
    ToolToken,
)
from .permissions import ROLE_LEVEL, audit, is_server, project_for
from .tool_profiles import PROFILES


def _safe_next(request, value: str) -> str:
    if value and url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return value
    return reverse("projects:index")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@require_http_methods(["GET", "POST"])
def register(request):
    if not is_server():
        return redirect("projects:index")
    invite_token = request.POST.get("invite") or request.GET.get("invite") or ""
    invitation = (
        Invitation.objects.filter(token_hash=_hash_token(invite_token)).first()
        if invite_token
        else None
    )
    if not getattr(settings, "WORKROOM_ALLOW_REGISTRATION", False) and not (
        invitation and invitation.is_live
    ):
        raise Http404("registration disabled")
    error = ""
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        if not allow_attempt(request, "register", username):
            return HttpResponse("尝试过于频繁，请 15 分钟后再试。", status=429)
        password = request.POST.get("password") or ""
        confirm = request.POST.get("password2") or ""
        if not username or len(username) > 150:
            error = "用户名不能为空，且不超过 150 个字符。"
        elif password != confirm:
            error = "两次输入的密码不一致。"
        elif User.objects.filter(username__iexact=username).exists():
            error = "这个用户名已经被使用。"
        else:
            try:
                validate_password(password)
            except ValidationError as exc:
                error = "；".join(exc.messages)
            else:
                candidate = User(username=username)
                try:
                    candidate.full_clean(exclude=["password"])
                except ValidationError:
                    error = "用户名格式不正确或已被使用。"
                    return render(
                        request, "projects/register.html", {"error": error, "invite": invite_token}
                    )
                user = User.objects.create_user(username=username, password=password)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                if invitation and invitation.is_live:
                    return redirect(reverse("projects:join_invite", args=[invite_token]))
                return redirect(_safe_next(request, request.POST.get("next") or ""))
    return render(
        request,
        "projects/register.html",
        {"error": error, "next": request.GET.get("next") or "", "invite": invite_token},
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    if not is_server():
        return redirect("projects:index")
    error = ""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        if not allow_attempt(request, "login", username):
            return HttpResponse("尝试过于频繁，请 15 分钟后再试。", status=429)
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None:
            error = "用户名或密码不对。"
        else:
            login(request, user)
            return redirect(_safe_next(request, next_url))
    return render(
        request,
        "projects/login.html",
        {
            "error": error,
            "next": next_url,
            "allow_registration": getattr(settings, "WORKROOM_ALLOW_REGISTRATION", False),
        },
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect(reverse("projects:login") if is_server() else reverse("projects:index"))


@require_http_methods(["GET", "POST"])
def join_invite(request, token: str):
    if not is_server():
        raise Http404("invite links require server mode")
    token_hash = _hash_token(token)
    invitation = Invitation.objects.select_related("project").filter(token_hash=token_hash).first()
    if invitation is None:
        return render(
            request,
            "projects/join.html",
            {"invalid": "邀请链接不存在或已被替换。"},
            status=404,
        )
    if not invitation.is_live:
        return render(
            request,
            "projects/join.html",
            {
                "invalid": "邀请已过期、已使用或已撤销，请让项目所有者重新生成。",
                "invitation": invitation,
            },
            status=410,
        )
    if not request.user.is_authenticated:
        return render(
            request,
            "projects/join.html",
            {
                "project": invitation.project,
                "invitation": invitation,
                "invite_token": token,
                "needs_account": True,
            },
        )
    if request.method == "POST":
        with transaction.atomic():
            locked = (
                Invitation.objects.select_for_update()
                .select_related("project")
                .filter(pk=invitation.pk)
                .first()
            )
            if locked is None or not locked.is_live:
                return render(
                    request,
                    "projects/join.html",
                    {"invalid": "邀请已被使用或已失效。"},
                    status=410,
                )
            membership, created = ProjectMembership.objects.get_or_create(
                project=locked.project,
                user=request.user,
                defaults={"role": locked.role},
            )
            if not created and ROLE_LEVEL[locked.role] > ROLE_LEVEL[membership.role]:
                membership.role = locked.role
                membership.save(update_fields=["role"])
            Member.objects.get_or_create(
                project=locked.project,
                user=request.user,
                defaults={
                    "kind": Member.Kind.HUMAN,
                    "name": request.user.get_username()[:80],
                },
            )
            locked.used_at = timezone.now()
            locked.used_by = request.user
            locked.save(update_fields=["used_at", "used_by"])
            audit(
                locked.project,
                request.user,
                "invite.join",
                f"role={locked.role} invite={locked.pk}",
            )
        return redirect(reverse("projects:space", args=[invitation.project_id]))
    return render(
        request,
        "projects/join.html",
        {"invitation": invitation, "project": invitation.project},
    )


@require_http_methods(["GET", "POST"])
@transaction.atomic
def team(request, pk: int):
    project = project_for(request, pk, owner=True)
    new_invite_url = ""
    new_token = ""
    error = ""
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "external":
            tool = request.POST.get('tool', '')
            if tool not in PROFILES or tool == 'custom':
                error = '请选择支持的外部工具。'
            else:
                member = Member.objects.create(project=project, tool=tool, kind=Member.Kind.EXTERNAL,
                    name=tool, role='执行', duty=Member.Duty.EXECUTE,
                    connection_id=uuid.uuid4(), connection_user=request.user)
                audit(project, request.user, 'member.external.add', f'member={member.pk} tool={tool}')
        elif action == "role":
            membership = get_object_or_404(
                ProjectMembership, pk=request.POST.get("membership_id"), project=project
            )
            role = request.POST.get("role") or ""
            if role not in dict(ProjectMembership.Role.choices):
                error = "角色不正确。"
            elif (
                membership.role == ProjectMembership.Role.OWNER
                and role != ProjectMembership.Role.OWNER
                and project.memberships.filter(role=ProjectMembership.Role.OWNER).count() <= 1
            ):
                error = "项目至少要保留一位所有者。"
            else:
                membership.role = role
                membership.save(update_fields=["role"])
                audit(
                    project,
                    request.user,
                    "membership.role",
                    f"user={membership.user_id} role={role}",
                )
        elif action == "remove":
            membership = get_object_or_404(
                ProjectMembership, pk=request.POST.get("membership_id"), project=project
            )
            if (
                membership.role == ProjectMembership.Role.OWNER
                and project.memberships.filter(role=ProjectMembership.Role.OWNER).count() <= 1
            ):
                error = "不能移除最后一位所有者。"
            else:
                Member.objects.filter(project=project, user=membership.user).update(
                    user=None, is_active=False
                )
                Member.objects.filter(project=project, connection_user=membership.user).update(is_active=False)
                audit(
                    project,
                    request.user,
                    "membership.remove",
                    f"user={membership.user_id}",
                )
                membership.delete()
        elif action == "invite":
            role = request.POST.get("role") or ProjectMembership.Role.VIEWER
            if role not in {
                ProjectMembership.Role.VIEWER,
                ProjectMembership.Role.EDITOR,
            }:
                error = "邀请角色只能是只读或编辑者。"
            else:
                raw = secrets.token_urlsafe(32)
                expires = timezone.now() + timedelta(
                    hours=int(getattr(settings, "WORKROOM_INVITE_TTL_HOURS", 72))
                )
                invitation = Invitation.objects.create(
                    project=project,
                    role=role,
                    token_hash=_hash_token(raw),
                    created_by=request.user,
                    expires_at=expires,
                )
                audit(
                    project,
                    request.user,
                    "invite.create",
                    f"role={role} invite={invitation.pk}",
                )
                new_invite_url = request.build_absolute_uri(
                    reverse("projects:join_invite", args=[raw])
                )
        elif action == "revoke_invite":
            invitation = get_object_or_404(
                Invitation, pk=request.POST.get("invite_id"), project=project
            )
            invitation.revoked_at = timezone.now()
            invitation.save(update_fields=["revoked_at"])
            audit(project, request.user, "invite.revoke", f"invite={invitation.pk}")
        elif action == "token":
            scope = request.POST.get("scope") or ToolToken.Scope.READ
            if scope not in {ToolToken.Scope.READ, ToolToken.Scope.EXECUTE}:
                error = "令牌权限不正确。"
            else:
                name = (request.POST.get("name") or "外部工具").strip()[:80]
                member = None
                raw_member = (request.POST.get("member") or "").strip()
                if raw_member:
                    member = project.members.filter(
                        pk=raw_member, kind=Member.Kind.EXTERNAL, is_active=True
                    ).first()
                    if member is None:
                        error = "只能绑定本项目的外部工具成员。"
                    elif member.connection_user_id not in (None, request.user.pk) or (
                        member.connection_user_id is None and member.connection_id is not None
                    ):
                        error = '请由实例所属用户生成自己的连接凭据。'
                if not error:
                    raw = "wrk_" + secrets.token_urlsafe(32)
                    try:
                        days = min(365, max(1, int(request.POST.get("days") or 30)))
                    except ValueError:
                        days = 30
                    if scope == ToolToken.Scope.EXECUTE and member is None:
                        error = "执行令牌必须绑定一个外部工具成员。"
                    if error:
                        return render(
                            request, "projects/team.html", {"project": project, "error": error}
                        )
                    token = ToolToken.objects.create(
                        project=project,
                        user=request.user,
                        member=member,
                        name=name,
                        token_hash=_hash_token(raw),
                        scope=scope,
                        expires_at=timezone.now() + timedelta(days=max(1, days)),
                    )
                    audit(
                        project,
                        request.user,
                        "token.create",
                        f"token={token.pk} scope={scope} member={member.pk if member else '-'}",
                    )
                    new_token = raw
        elif action == "revoke_token":
            token = get_object_or_404(ToolToken, pk=request.POST.get("token_id"), project=project)
            token.revoked_at = timezone.now()
            token.save(update_fields=["revoked_at"])
            audit(project, request.user, "token.revoke", f"token={token.pk}")
        else:
            error = "未知操作。"

    memberships = project.memberships.select_related("user").all()
    invitations = project.invitations.select_related("created_by").all()[:30]
    tokens = project.tool_tokens.select_related("member", "user").all()[:30]
    return render(
        request,
        "projects/team.html",
        {
            "project": project,
            "memberships": memberships,
            "owner_controls": True,
            "invitations": invitations,
            "tokens": tokens,
            "new_invite_url": new_invite_url,
            "new_token": new_token,
            "error": error,
            "external_members": project.members.filter(kind=Member.Kind.EXTERNAL, is_active=True).filter(
                Q(connection_user=request.user) | Q(connection_user__isnull=True, connection_id__isnull=True)),
            "role_choices": ProjectMembership.Role.choices,
        },
    )


@require_GET
def healthz(request):
    from django.db import connection
    from django.http import JsonResponse

    from .models import Delivery, ReplyJob, WorkerHeartbeat

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - health must report, not crash
        return JsonResponse({"ok": False, "error": "database"}, status=503)
    now = timezone.now()
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({"ok": True, "mode": getattr(settings, "WORKROOM_MODE", "local")})
    workers = [
        {
            "id": item.worker_id,
            "last_seen": item.last_seen_at.isoformat(),
            "stale": (now - item.last_seen_at).total_seconds() > 120,
        }
        for item in WorkerHeartbeat.objects.all()[:10]
    ]
    return JsonResponse(
        {
            "ok": True,
            "mode": getattr(settings, "WORKROOM_MODE", "local"),
            "queued": ReplyJob.objects.filter(status=ReplyJob.Status.QUEUED).count(),
            "running": ReplyJob.objects.filter(status=ReplyJob.Status.RUNNING).count(),
            "pending_deliveries": Delivery.objects.filter(status=Delivery.Status.PENDING).count(),
            "workers": workers,
        }
    )
