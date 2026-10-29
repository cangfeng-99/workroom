"""One-click MCP setup: write the WorkRoom entry into local client configs.

Only the three known paths are touched, existing files are backed up first, and
the merge preserves everything else in the file.
"""

from __future__ import annotations

import json
import shutil
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from django.conf import settings


class ClientError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def client_specs() -> dict[str, dict]:
    home = Path(settings.MCP_HOME)
    return {
        'cursor': {
            'label': 'Cursor',
            'kind': 'json',
            'dir': home / '.cursor',
            'path': home / '.cursor' / 'mcp.json',
        },
        'codex': {
            'label': 'Codex',
            'kind': 'toml',
            'dir': home / '.codex',
            'path': home / '.codex' / 'config.toml',
        },
        'workbuddy': {
            'label': 'WorkBuddy',
            'kind': 'json',
            'dir': home / '.workbuddy',
            'path': home / '.workbuddy' / 'mcp.json',
        },
    }


def mcp_command() -> tuple[str, list[str]]:
    """The command a client should launch (dev script or packaged exe with --mcp)."""
    if getattr(sys, 'frozen', False):
        return sys.executable, ['--mcp', '--data-dir', str(settings.DATA_DIR)]
    return sys.executable, [str(Path(settings.BASE_DIR) / 'mcp_server.py')]


def _is_configured(spec: dict) -> bool:
    path: Path = spec['path']
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return False
    try:
        if spec['kind'] == 'json':
            data = json.loads(text)
            return isinstance(data, dict) and 'workroom' in (
                data.get('mcpServers') or {}
            )
        data = tomllib.loads(text)
        return 'workroom' in (data.get('mcp_servers') or {})
    except (ValueError, tomllib.TOMLDecodeError):
        return 'workroom' in text


def status() -> list[dict]:
    items = []
    for key, spec in client_specs().items():
        configured = _is_configured(spec)
        items.append(
            {
                'key': key,
                'label': spec['label'],
                'path': str(spec['path']),
                'installed': spec['dir'].exists(),
                'configured': configured,
            }
        )
    return items


def _merge_toml(text: str, command: str, args: list[str]) -> str:
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            name = stripped.strip('[]').strip()
            skipping = name == 'mcp_servers.workroom' or name.startswith(
                'mcp_servers.workroom.'
            )
            if skipping:
                continue
        if not skipping:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    arg_list = ', '.join(json.dumps(str(item), ensure_ascii=False) for item in args)
    block = [
        '',
        '[mcp_servers.workroom]',
        f'command = {json.dumps(command, ensure_ascii=False)}',
        f'args = [{arg_list}]',
        '',
    ]
    return '\n'.join(out + block)


def connect(key: str) -> str:
    spec = client_specs().get(key)
    if spec is None:
        raise ClientError('未知客户端。')
    if not spec['dir'].exists():
        raise ClientError(f'没有检测到 {spec["label"]}，先打开一次它再接入。')

    path: Path = spec['path']
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    command, args = mcp_command()

    if spec['kind'] == 'json':
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError as exc:
            raise ClientError('现有配置不是合法 JSON，请手动处理。') from exc
        if not isinstance(data, dict):
            raise ClientError('现有配置不是 JSON 对象，请手动处理。')
        servers = data.setdefault('mcpServers', {})
        if not isinstance(servers, dict):
            raise ClientError('现有配置里的 mcpServers 不是对象，请手动处理。')
        servers['workroom'] = {'command': command, 'args': args}
        new_text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    else:
        new_text = _merge_toml(text, command, args)

    if path.exists():
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        shutil.copy2(path, path.with_name(path.name + f'.bak-{stamp}'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding='utf-8')
    return str(path)
