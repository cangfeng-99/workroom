#!/usr/bin/env python
"""Minimal MCP stdio server for WorkRoom.

External harnesses (Codex / Cursor / WorkBuddy) launch this script and speak
newline-delimited JSON-RPC 2.0 over stdin/stdout. It exposes the project plan,
tasks and library, and lets the harness create tasks or report progress.

Usage:
    python mcp_server.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from tool_schema import PROTOCOL, TOOLS

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

_mcp_module = None
_load_lock = threading.Lock()


def _log(text: str) -> None:
    """Small rolling log for troubleshooting client handshakes."""
    try:
        log = Path(os.environ.get('WORKROOM_DATA_DIR') or (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'WorkRoom')) / 'mcp.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.exists() and log.stat().st_size > 200_000:
            log.write_text('', encoding='utf-8')
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with log.open('a', encoding='utf-8') as handle:
            handle.write(stamp + ' ' + text + chr(10))
    except OSError:
        pass


def _load():
    """Django + models are only imported when a tool is actually called.

    The handshake must answer instantly; Django's first import can take seconds
    on Windows, which makes clients time out during ``initialize``.
    """
    global _mcp_module
    if os.environ.get('WORKROOM_DESKTOP_MCP') == '1':
        if _mcp_module is None:
            from desktop_mcp import DesktopBridge

            _mcp_module = DesktopBridge()
        return _mcp_module
    if os.environ.get('WORKROOM_SERVER_URL'):
        if _mcp_module is None:
            from remote_bridge import RemoteBridge
            _mcp_module = RemoteBridge()
        return _mcp_module
    if _mcp_module is not None:
        return _mcp_module
    with _load_lock:
        if _mcp_module is None:
            import django

            django.setup()
            from apps.projects import mcp as module

            _mcp_module = module
    return _mcp_module




def _ok(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def handle(request: dict):
    method = request.get('method')
    request_id = request.get('id')

    if method == 'initialize':
        # Warm Django in the background so the first tool call is not slow.
        threading.Thread(target=_load, daemon=True).start()
        return _ok(
            request_id,
            {
                'protocolVersion': PROTOCOL,
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'workroom', 'version': '0.1.0'},
            },
        )
    if method == 'notifications/initialized':
        return None
    if method == 'ping':
        return _ok(request_id, {})
    if method == 'tools/list':
        return _ok(request_id, {'tools': TOOLS})
    if method == 'tools/call':
        params = request.get('params') or {}
        name = params.get('name') or ''
        arguments = params.get('arguments') or {}
        try:
            module = _load()
            try:
                text = module.call_tool(name, arguments)
            except Exception as exc:  # noqa: BLE001 - tool errors become text
                # Bridges do not expose McpError, so read ``message`` defensively
                # instead of touching ``module.McpError`` (AttributeError there
                # used to report a misleading "工具执行失败").
                message = getattr(exc, 'message', None) or str(exc) or exc.__class__.__name__
                return _ok(
                    request_id,
                    {
                        'content': [{'type': 'text', 'text': message}],
                        'isError': True,
                    },
                )
            return _ok(
                request_id,
                {'content': [{'type': 'text', 'text': text}], 'isError': False},
            )
        except Exception as exc:  # noqa: BLE001 - surface a readable message
            return _ok(
                request_id,
                {
                    'content': [{'type': 'text', 'text': f'工具执行失败：{exc}'}],
                    'isError': True,
                },
            )
    return _error(request_id, -32601, f'Unknown method: {method}')


def _read_request(stream):
    """Read one JSON-RPC message, accepting newline or Content-Length framing."""
    first = stream.readline()
    while first and not first.strip():
        first = stream.readline()
    if not first:
        return None, False

    stripped = first.strip()
    if stripped.lower().startswith(b'content-length:'):
        try:
            length = int(stripped.split(b':', 1)[1])
        except (IndexError, ValueError):
            return None, True
        while True:
            header = stream.readline()
            if not header or not header.strip():
                break
        body = stream.read(length)
        try:
            return json.loads(body.decode('utf-8')), True
        except (ValueError, UnicodeDecodeError):
            return None, True

    try:
        return json.loads(stripped.decode('utf-8')), False
    except (ValueError, UnicodeDecodeError):
        return None, False


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', newline=chr(10))
        sys.stdin.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    _log(f'startup pid={os.getpid()}')

    while True:
        request, framed = _read_request(stdin)
        if request is None:
            break
        if not isinstance(request, dict):
            continue
        method = request.get('method', '')
        _log(f'recv {method}')
        response = handle(request)
        if response is None:
            continue
        _log(f'sent {method}')
        payload = json.dumps(response, ensure_ascii=False).encode('utf-8')
        crlf = bytes((13, 10))
        if framed:
            header = b'Content-Length: ' + str(len(payload)).encode('ascii') + crlf + crlf
            stdout.write(header + payload)
        else:
            stdout.write(payload + bytes((10,)))
        stdout.flush()


if __name__ == '__main__':
    main()
