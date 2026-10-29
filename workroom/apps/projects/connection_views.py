"""Per-user tool instances and one-time credential/configuration output."""

import re
import secrets
import uuid
from datetime import timedelta

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .auth_views import _hash_token
from .connection_config import configuration
from .models import Member, ToolToken
from .permissions import audit, is_server, project_for, role_of
from .tool_profiles import CAPABILITIES, PROFILES


class ConnectionForm(forms.Form):
    tool = forms.ChoiceField(label="工具类型", choices=list(PROFILES.items()))
    custom_tool = forms.CharField(
        label="自定义工具标识",
        required=False,
        max_length=20,
        help_text="选择自定义时填写，例如 my-agent。",
    )
    name = forms.CharField(
        label="实例名称", max_length=80, help_text="例如 张三的 Mac · Claude Code"
    )
    device_name = forms.CharField(label="实际执行设备", max_length=80)
    platform = forms.ChoiceField(
        label="执行设备系统",
        choices=[
            ("mac", "macOS"),
            ("windows", "Windows"),
            ("linux", "Linux"),
            ("harmony", "HarmonyOS"),
            ("other", "其他"),
        ],
    )
    capabilities = forms.MultipleChoiceField(
        label="该实例已具备的能力（用户声明）",
        required=False,
        choices=CAPABILITIES,
        widget=forms.CheckboxSelectMultiple,
    )

    def clean(self):
        data = super().clean()
        if data.get("tool") == "custom" and not re.fullmatch(
            r"[a-z][a-z0-9-]{0,19}", data.get("custom_tool", "")
        ):
            raise forms.ValidationError("自定义标识须以小写字母开头，只含字母、数字、短横线。")
        if data.get("tool") == "claude-code" and data.get("platform") == "harmony":
            raise forms.ValidationError(
                "Claude Code未提供鸿蒙支持；请选择它实际运行的电脑，可从鸿蒙网页管理。"
            )
        return data


@require_http_methods(["GET", "POST"])
def connections(request, pk):
    from .quick_connections import client_choices, local_setup_allowed, platform_name

    if not is_server():
        raise Http404()
    project = project_for(request, pk, write=request.method == "POST")
    form = ConnectionForm(request.POST if request.POST.get("action") == "add" else None)
    output = command = ""
    configured_member = None
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "add" and form.is_valid():
            with transaction.atomic():
                data = form.cleaned_data
                member = Member.objects.create(
                    project=project,
                    kind="external",
                    tool=data["custom_tool"] if data["tool"] == "custom" else data["tool"],
                    name=data["name"],
                    role="执行",
                    connection_id=uuid.uuid4(),
                    connection_user=request.user,
                    device_name=data["device_name"],
                    platform=data["platform"],
                    capabilities=data["capabilities"],
                )
                audit(
                    project,
                    request.user,
                    "connection.add",
                    f"member={member.pk} instance={member.connection_id}",
                )
            return redirect(reverse("projects:connections", args=[pk]) + f"#connection-{member.pk}")
        elif action in {"configure", "revoke"}:
            member = get_object_or_404(
                Member,
                project=project,
                kind="external",
                is_active=True,
                pk=request.POST.get("member"),
            )
            if member.connection_user_id != request.user.pk:
                raise PermissionDenied("请由该实例所属用户生成或管理自己的连接凭据。")
            if action == "revoke":
                ToolToken.objects.filter(
                    member=member, user=request.user, revoked_at__isnull=True
                ).update(revoked_at=timezone.now())
                audit(project, request.user, "connection.revoke", f"member={member.pk}")
                return redirect("projects:connections", pk=pk)
            scope = request.POST.get("scope", "read")
            if scope not in {"read", "execute"}:
                raise PermissionDenied("连接权限无效。")
            raw = "wrk_" + secrets.token_urlsafe(32)
            ToolToken.objects.create(
                project=project,
                user=request.user,
                member=member,
                scope=scope,
                name=member.name,
                token_hash=_hash_token(raw),
                expires_at=timezone.now() + timedelta(days=30),
            )
            output, command = configuration(request, member, raw)
            configured_member = member
            audit(
                project, request.user, "connection.configure", f"member={member.pk} scope={scope}"
            )
    response = render(
        request,
        "projects/connections.html",
        dict(
            project=project,
            form=form,
            instances=project.members.filter(kind="external", is_active=True).select_related(
                "connection_user"
            ),
            can_edit=role_of(request.user, project) in {"owner", "editor"},
            owner_controls=role_of(request.user, project) == "owner",
            tools=client_choices(request, project),
            auto_local=local_setup_allowed(request),
            device_platform=platform_name(request),
            notice=request.session.pop('connection_notice', ''),
            configuration=output,
            command=command,
            configured_member=configured_member,
        ),
    )
    response["Cache-Control"] = "no-store"
    # Keep same-origin POSTs compatible with Django CSRF. No credential is in URLs.
    response["Referrer-Policy"] = "same-origin"
    return response


def _detect_local_agents() -> dict:
    import json
    import shutil
    from datetime import datetime
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    codex_root = Path.home() / 'AppData' / 'Local' / 'OpenAI' / 'Codex' / 'bin'
    codex = sorted(codex_root.glob('*/codex.exe')) if codex_root.exists() else []
    bridges = []
    for state_path in sorted((root / '.tools').glob('bridge_state_*.json')):
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
            stamp = datetime.fromisoformat(state.get('updated_at', ''))
            state['online'] = (datetime.now() - stamp).total_seconds() < 90
        except (ValueError, OSError):
            continue
        bridges.append(state)
    return {
        'codex': str(codex[-1]) if codex else '',
        'codebuddy': shutil.which('codebuddy') or '',
        'a2a': (Path(r'D:\A2A-Hub') / 'run.py').exists(),
        'bridges': bridges,
    }


@require_GET
def agents(request, pk):
    from django.shortcuts import render

    project = project_for(request, pk)
    return render(
        request,
        'projects/agents.html',
        {'project': project, 'local': _detect_local_agents()},
    )


@require_GET
def agents_status(request, pk):
    project = project_for(request, pk)
    data = _detect_local_agents()
    data['project'] = project.pk
    return JsonResponse(data)
