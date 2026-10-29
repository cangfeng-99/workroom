"""Bearer-token HTTP tool bridge used by remote MCP clients."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from django.core.exceptions import RequestDataTooBig, ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import mcp
from .delivery import ClaimConflict, DeliveryError
from .models import ProjectMembership, ToolToken

READ_TOOLS = {
    'next_task',
    "list_projects",
    "get_project",
    "list_tasks",
    "get_latest_plan",
    "get_inbox",
    "wait_for_work",
    "get_task_context",
    "get_library_entry",
    "whoami",
    "list_deliveries",
}
EXECUTE_TOOLS = {
    'review_delivery',
    "confirm_task_context",
    "create_task",
    "update_task_status",
    "add_library_entry",
    "claim_task",
    "heartbeat_task",
    "submit_result",
    "post_message",
    "report_progress",
    "release_task",
}
MAX_BODY = 64 * 1024


@dataclass
class ToolContext:
    token: ToolToken
    project_id: int
    user: object
    member: object
    scope: str

    @property
    def can_execute(self) -> bool:
        return self.scope == ToolToken.Scope.EXECUTE

    def require_execute(self) -> None:
        if not self.can_execute:
            raise PermissionError("这个令牌只有只读权限。")


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bearer(request) -> str:
    header = request.META.get("HTTP_AUTHORIZATION") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def authenticate(request) -> ToolContext | None:
    raw = _bearer(request)
    if not raw or not raw.startswith("wrk_") or len(raw) > 256:
        return None
    token = (
        ToolToken.objects.select_related("project", "user", "member")
        .filter(token_hash=_hash(raw))
        .first()
    )
    if token is None or not token.is_live:
        return None
    if token.user is not None:
        if not token.user.is_active:
            return None
        membership = ProjectMembership.objects.filter(
            project=token.project, user=token.user
        ).first()
        if membership is None:
            return None
        if (
            token.scope == ToolToken.Scope.EXECUTE
            and membership.role == ProjectMembership.Role.VIEWER
        ):
            return None
    else:
        return None
    if token.scope == ToolToken.Scope.EXECUTE and token.member is None:
        return None
    if token.member is not None and (
        not token.member.is_active or token.member.project_id != token.project_id
    ):
        return None
    if token.member is not None and (
        token.member.connection_user_id not in (None, token.user_id)
        or (token.member.connection_user_id is None and token.member.connection_id is not None)
    ):
        return None
    return ToolContext(
        token=token,
        project_id=token.project_id,
        user=token.user,
        member=token.member,
        scope=token.scope,
    )


def mark_success(ctx):
    now = timezone.now()
    ToolToken.objects.filter(pk=ctx.token.pk).update(last_seen_at=now)
    if ctx.member is not None:
        from .models import Member
        Member.objects.filter(pk=ctx.member.pk).update(last_connected_at=now)


@csrf_exempt
@require_POST
def call_tool(request, name: str):
    try:
        body = request.body
    except RequestDataTooBig:
        return JsonResponse({"ok": False, "error": "请求体过大。"}, status=413)
    if len(body) > MAX_BODY:
        return JsonResponse({"ok": False, "error": "请求体过大。"}, status=413)
    if name not in READ_TOOLS and name not in EXECUTE_TOOLS:
        return JsonResponse({"ok": False, "error": "未知工具。"}, status=400)
    ctx = authenticate(request)
    if ctx is None:
        return JsonResponse({"ok": False, "error": "认证失败或令牌已失效。"}, status=401)
    if name in EXECUTE_TOOLS and not ctx.can_execute:
        return JsonResponse({"ok": False, "error": "令牌没有执行权限。"}, status=403)
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "JSON 格式不正确。"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "参数必须是 JSON 对象。"}, status=400)
    try:
        text = mcp.call_tool(name, data, ctx=ctx)
    except ClaimConflict as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": exc.message,
                "claim": str(exc.claim.run_id),
                "conflict": True,
            },
            status=409,
        )
    except mcp.McpError as exc:
        status = 404 if "找不到" in exc.message else 400
        return JsonResponse({"ok": False, "error": exc.message}, status=status)
    except PermissionError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=403)
    except DeliveryError as exc:
        return JsonResponse({"ok": False, "error": exc.message}, status=400)
    except (ValidationError, ValueError, TypeError, OverflowError):
        return JsonResponse({"ok": False, "error": "工具参数格式不正确。"}, status=400)
    mark_success(ctx)
    return JsonResponse({"ok": True, "tool": name, "result": text})
