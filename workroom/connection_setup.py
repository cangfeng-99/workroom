"""Standalone client setup, shared by local preview and downloaded helpers.

Only fixed user-profile paths and project-namespaced HTTP MCP entries are allowed.
No client commands, models or network requests are executed.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile

try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit('连接助手需要Python 3.11及以上，请安装后重试。') from None
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

TARGETS = {
    'codex': ('.codex/config.toml', '.codex', 'toml'),
    'workbuddy': ('.workbuddy/mcp.json', '.workbuddy', 'json'),
    'cursor': ('.cursor/mcp.json', '.cursor', 'json'),
    'claude-code': ('.claude.json', '.claude', 'json'),
}


class SetupError(Exception):
    pass


def available_clients(home=None):
    home = Path(home or Path.home())
    return {key: (home / directory).is_dir() or (home / relative).is_file()
            for key, (relative, directory, _) in TARGETS.items()}


def _without_entry(data, name):
    data = copy.deepcopy(data)
    servers = data.get('mcp_servers', {})
    servers.pop(name, None)
    if not servers:
        data.pop('mcp_servers', None)
    return data


def _toml_merge(text, addition, name):
    before = tomllib.loads(text)
    entry = tomllib.loads(addition)['mcp_servers'][name]
    begin, end = f'# BEGIN WorkRoom {name}', f'# END WorkRoom {name}'
    block = f'{begin}\n{addition.rstrip()}\n{end}\n'
    if name in before.get('mcp_servers', {}):
        if text.count(begin) != 1 or text.count(end) != 1:
            raise SetupError('同名配置已存在且不属于连接助手，请在高级配置中核对。')
        start, stop = text.index(begin), text.index(end) + len(end)
        if start >= stop:
            raise SetupError('连接配置标记不完整，请从备份核对。')
        result = text[:start] + block.rstrip('\n') + text[stop:]
    else:
        result = text.rstrip() + '\n\n' + block
    after = tomllib.loads(result)
    if after['mcp_servers'][name] != entry or _without_entry(before, name) != _without_entry(after, name):
        raise SetupError('无法完整保留现有TOML配置，已停止写入。')
    return result


def _validate_entry(entry, kind):
    allowed = {'url', 'http_headers'} if kind == 'toml' else {'url', 'type', 'headers'}
    if not isinstance(entry, dict) or set(entry) - allowed:
        raise SetupError('连接助手只接受HTTP项目连接。')
    parsed = urlsplit(entry.get('url', ''))
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError('连接地址无效。')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}):
        raise SetupError('远程连接必须使用HTTPS。')
    headers = entry.get('http_headers' if kind == 'toml' else 'headers')
    if not isinstance(headers, dict) or set(headers) != {'Authorization'} or not isinstance(headers['Authorization'], str):
        raise SetupError('项目授权配置无效。')


def _profile_path(home, relative):
    home = Path(home or Path.home()).resolve()
    path = home / relative
    current = home
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise SetupError('配置路径是链接或不在用户目录内，已停止写入。')
    if not path.resolve().is_relative_to(home) or (path.exists() and path.stat().st_nlink > 1):
        raise SetupError('配置路径是链接或不在用户目录内，已停止写入。')
    return home, path


def saved_token(tool, name, url, *, home=None):
    """Read an existing local credential; the caller must validate its DB identity."""
    try:
        relative, _, kind = TARGETS[tool]
        _, path = _profile_path(home, relative)
        if not path.is_file():
            return ''
        source = path.read_text(encoding='utf-8-sig')
        data = tomllib.loads(source) if kind == 'toml' else json.loads(source)
        entry = data['mcp_servers' if kind == 'toml' else 'mcpServers'][name]
        _validate_entry(entry, kind)
        if entry['url'] != url:
            return ''
        value = entry['http_headers' if kind == 'toml' else 'headers']['Authorization']
        return value[7:] if value.startswith('Bearer wrk_') else ''
    except (KeyError, TypeError, ValueError, OSError, SetupError):
        return ''


def install_connection(payload, *, home=None):
    tool, name = payload.get('tool'), payload.get('server_name', '')
    if tool not in TARGETS or not re.fullmatch(r'workroom-[a-z0-9-]{1,60}', name):
        raise SetupError('不支持的工具或项目连接名称。')
    relative, _, kind = TARGETS[tool]
    home, path = _profile_path(home, relative)
    if not available_clients(home).get(tool):
        raise SetupError('没有检测到该工具的用户配置，请安装并打开一次后重试。')
    lock = path.with_name(path.name + '.workroom-lock')
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        raise SetupError('配置正被使用或无法写入，请稍后重试。') from exc
    temporary = None
    try:
        os.close(lock_fd)
        existed = path.exists()
        text = path.read_text(encoding='utf-8-sig') if existed else ''
        addition = payload['configuration']
        if kind == 'toml':
            entry = tomllib.loads(addition)['mcp_servers'][name]
            _validate_entry(entry, kind)
            result = _toml_merge(text, addition, name)
        else:
            data = json.loads(text) if text.strip() else {}
            entry = json.loads(addition)['mcpServers'][name]
            _validate_entry(entry, kind)
            if not isinstance(data, dict) or not isinstance(data.get('mcpServers', {}), dict):
                raise SetupError('现有mcpServers格式无效，请在高级配置中核对。')
            data.setdefault('mcpServers', {})[name] = entry
            result = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
        if path.exists() != existed or (existed and path.read_text(encoding='utf-8-sig') != text):
            raise SetupError('配置在连接期间已被其它程序修改，请重新连接。')
        if existed:
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
            backup = path.with_name(path.name + '.bak-' + stamp)
            shutil.copy2(path, backup)
            backup.chmod(0o600)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.workroom-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(result)
        temporary.chmod(0o600)
        os.replace(temporary, path)
        return str(path)
    except SetupError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SetupError('现有配置无法安全合并，原文件已保留；请在高级配置中检查。') from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        lock.unlink(missing_ok=True)


def main(payload):
    try:
        install_connection(payload)
    except SetupError as exc:
        print(str(exc))
        return 1
    print('WorkRoom配置已保存，原有配置已保留。请重新加载工具的MCP连接或开启新会话，再调用whoami；项目页会显示成功调用时间。')
    return 0
