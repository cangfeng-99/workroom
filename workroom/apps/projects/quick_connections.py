"""One-click project setup. Production never reads or writes the server's home."""
import base64
import ipaddress
import json
import platform
import secrets
import textwrap
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from connection_setup import TARGETS, SetupError, available_clients, install_connection, saved_token

from .auth_views import _hash_token
from .connection_config import configuration
from .models import Member, Project, ToolToken
from .permissions import audit, is_server, project_for
from .tool_profiles import PROFILES


def local_setup_allowed(request):
    if not getattr(settings, 'WORKROOM_LOCAL_PREVIEW', False):
        return False
    try:
        return (ipaddress.ip_address(request.META.get('REMOTE_ADDR', '')).is_loopback
                and urlsplit('http://' + request.get_host()).hostname in {'127.0.0.1', 'localhost', '::1'})
    except ValueError:
        return False


def platform_name(request):
    agent = request.headers.get('User-Agent', '').lower()
    return 'mac' if 'mac' in agent else 'windows' if 'windows' in agent else 'linux' if 'linux' in agent else 'other'


def local_client_home(tool):
    homes = getattr(settings, 'WORKROOM_CLIENT_CONFIG_HOMES', {})
    return Path(homes.get(tool) or settings.MCP_HOME)


def client_choices(request, project):
    local = local_setup_allowed(request)
    detected = {key: available_clients(local_client_home(key)).get(key, False) for key in TARGETS} if local else {}
    members = list(project.members.filter(kind='external', is_active=True, connection_user=request.user))
    tokens = list(ToolToken.objects.filter(member__in=members, revoked_at__isnull=True, expires_at__gt=timezone.now()))
    active = {token.member_id for token in tokens}
    verified = {token.member_id for token in tokens if token.last_seen_at}
    result = []
    for key, label in PROFILES.items():
        if key == 'custom':
            continue
        member = next((m for m in members if m.tool == key), None)
        mode = 'local' if detected.get(key) else 'cursor' if key == 'cursor' else 'download' if key in TARGETS else 'manual'
        result.append(dict(key=key, label=label, mode=mode, member=member,
            configured=bool(member and member.pk in active), connected=bool(member and member.pk in verified),
            action='一键连接' if mode == 'local' else '在Cursor中连接' if mode == 'cursor' else '下载连接助手' if mode == 'download' else '高级接入'))
    return result


def helper_download(payload, target):
    source = (Path(settings.BASE_DIR) / 'connection_setup.py').read_text(encoding='utf-8')
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    source += f"\nimport base64\nraise SystemExit(main(json.loads(base64.b64decode('{encoded}'))))\n"
    if target == 'windows':
        encoded_source = base64.b64encode(source.encode('utf-8')).decode()
        nonce = uuid.uuid4().hex
        body = ('@echo off\r\nsetlocal\r\n'
                f'set "WORKROOM_SETUP_FILE=%TEMP%\\workroom-connect-{nonce}.py"\r\n'
                'set "WORKROOM_SETUP_SOURCE=%~f0"\r\n'
                'powershell.exe -NoProfile -NonInteractive -Command '
                '"$ErrorActionPreference=\'Stop\'; $p=$env:WORKROOM_SETUP_FILE; $result=1; try { '
                '$s=[IO.File]::ReadAllText($env:WORKROOM_SETUP_SOURCE); '
                '$b=$s.Substring($s.LastIndexOf(\'WORKROOM_SETUP_PAYLOAD\')+22); '
                '[IO.File]::WriteAllBytes($p,[Convert]::FromBase64String($b)); '
                'if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 $p } else { & python $p }; '
                '$result=$LASTEXITCODE } catch { Write-Host \'Unable to start setup. Python 3.11+ is required.\' } '
                'finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }; exit $result"\r\n'
                'set "WORKROOM_SETUP_STATUS=%ERRORLEVEL%"\r\n'
                'pause\r\nexit /b %WORKROOM_SETUP_STATUS%\r\n'
                'WORKROOM_SETUP_PAYLOAD\r\n' + '\r\n'.join(textwrap.wrap(encoded_source, 120)) + '\r\n')
        suffix = 'cmd'
    elif target in {'mac', 'linux'}:
        body = ('#!/bin/sh\nset -eu\n'
                'command -v python3 >/dev/null 2>&1 || { printf "%s\\n" "Python 3.11+ is required."; exit 1; }\n'
                "python3 - <<'WORKROOM_SETUP'\n" + source + '\nWORKROOM_SETUP\n')
        suffix = 'command' if target == 'mac' else 'sh'
    else:
        raise SetupError('请选择Windows、Mac或Linux执行设备。')
    response = HttpResponse(body.encode('utf-8'), content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="Connect-WorkRoom-{payload["tool"]}.{suffix}"'
    return response


def private(response):
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'same-origin'
    return response


@require_POST
def quick_connect(request, pk, tool):
    if not is_server() or tool not in TARGETS:
        raise Http404()
    project = project_for(request, pk, write=True)
    mode = request.POST.get('mode', 'local')
    if mode not in {'local', 'download', 'cursor'}:
        return private(JsonResponse({'error': '连接方式无效。'}, status=400))
    if mode == 'local' and not local_setup_allowed(request):
        raise PermissionDenied('此服务不是本机预览，请在自己的设备运行连接助手。')
    if mode == 'cursor' and tool != 'cursor':
        raise Http404()
    scope = request.POST.get('scope', 'execute')
    if scope not in {'read', 'execute'}:
        return private(JsonResponse({'error': '连接权限无效。'}, status=400))
    device_platform = platform.system().lower() if mode == 'local' else request.POST.get('platform', platform_name(request))
    device_platform = {'darwin': 'mac'}.get(device_platform, device_platform)
    device_platform = device_platform if device_platform in {'windows', 'mac', 'linux'} else 'other'
    if mode == 'local':
        device = (platform.node() or '本机')[:80]
    else:
        browser_device = request.session.get('connection_device') or uuid.uuid4().hex
        request.session['connection_device'] = browser_device
        device = f'{device_platform} · {browser_device[:8]}'
    try:
        with transaction.atomic():
            Project.objects.select_for_update().get(pk=project.pk)
            member = Member.objects.filter(project=project, connection_user=request.user, kind='external', tool=tool, device_name=device, is_active=True).first()
            if member is None:
                member = Member.objects.create(project=project, connection_user=request.user,
                    connection_id=uuid.uuid4(), kind='external', tool=tool, device_name=device,
                    platform=device_platform, name=f'{request.user.get_username()} · {PROFILES[tool]} · {device}'[:80], role='执行')
            name = f'workroom-p{project.pk}-{member.connection_id.hex[:8]}'
            token = None
            raw = ''
            if mode == 'local':
                raw = saved_token(tool, name, request.build_absolute_uri('/mcp/'), home=local_client_home(tool))
                if raw:
                    token = ToolToken.objects.filter(project=project, user=request.user, member=member,
                        scope=scope, token_hash=_hash_token(raw)).first()
                    if token is not None and not token.is_live:
                        token = None
            if token is None:
                raw = 'wrk_' + secrets.token_urlsafe(32)
                token = ToolToken.objects.create(project=project, user=request.user, member=member,
                    scope=scope, name=member.name, token_hash=_hash_token(raw), expires_at=timezone.now()+timedelta(days=30))
            text, _ = configuration(request, member, raw, server_name=name)
            payload = dict(tool=tool, server_name=name, configuration=text)
            if mode == 'local':
                install_connection(payload, home=local_client_home(tool))
                # A same-scope reconnect must not invalidate an already loaded client.
                # Explicit revocation and permission changes still take effect.
                ToolToken.objects.filter(member=member, user=request.user, revoked_at__isnull=True).exclude(scope=scope).update(revoked_at=timezone.now())
                response = JsonResponse({'message': '本机配置已保存，有效凭据会复用。请在AI应用的MCP设置中重新加载连接；此按钮不会重启客户端。', 'state': 'configured', 'member':member.pk})
                audit(project, request.user, 'connection.install', f'member={member.pk} tool={tool}')
            elif mode == 'download':
                response = helper_download(payload, device_platform)
                audit(project, request.user, 'connection.helper', f'member={member.pk} tool={tool}')
            else:
                entry = json.loads(text)['mcpServers'][name]
                encoded = base64.b64encode(json.dumps(entry).encode()).decode()
                install_url = 'cursor://anysphere.cursor-deeplink/mcp/install?' + urlencode({'name':name, 'config':encoded})
                response = JsonResponse({'install_url': install_url, 'state':'pending', 'member':member.pk, 'message':'请在Cursor中确认安装，完成后回到这里。'})
                audit(project, request.user, 'connection.deeplink', f'member={member.pk} tool={tool}')
            response['X-WorkRoom-Member'] = str(member.pk)
    except SetupError as exc:
        return private(JsonResponse({'error':str(exc)}, status=400))
    if mode == 'local' and 'application/json' not in request.headers.get('Accept', ''):
        request.session['connection_notice'] = '本机配置已保存。请在AI应用的MCP设置中重新加载连接。'
        response = redirect('projects:connections', pk=pk)
    return private(response)


@require_GET
def connection_status(request, pk):
    if not is_server():
        raise Http404()
    project = project_for(request, pk)
    seen = {token.member_id: token.last_seen_at for token in ToolToken.objects.filter(project=project, user=request.user, revoked_at__isnull=True, expires_at__gt=timezone.now(), last_seen_at__isnull=False)}
    return private(JsonResponse({'instances': [
        {'id': member.pk, 'tool':member.tool, 'last_connected_at':seen[member.pk].isoformat() if member.pk in seen else None}
        for member in project.members.filter(kind='external', is_active=True, connection_user=request.user)
    ]}))
