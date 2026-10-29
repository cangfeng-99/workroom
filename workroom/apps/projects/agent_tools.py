"""Read-only project tools for the agent loop.

Everything is confined to ``settings.AGENT_ROOT``. Secrets, databases, binaries
and dependency folders are blocked, files are size-capped, and no write or shell
tool exists on purpose — execution is delegated to external agents later.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

BLOCKED_DIRS = {
    '.git',
    '.idea',
    '.next',
    '.venv',
    '__pycache__',
    'build',
    'dist',
    'node_modules',
    'venv',
}
BLOCKED_NAMES = {'id_rsa', 'id_ed25519', 'id_dsa'}
BLOCKED_SUFFIXES = {
    '.7z',
    '.db',
    '.gif',
    '.ico',
    '.jpeg',
    '.jpg',
    '.key',
    '.mp4',
    '.pdf',
    '.pem',
    '.pfx',
    '.png',
    '.pyc',
    '.sqlite3',
    '.ttf',
    '.webp',
    '.woff',
    '.woff2',
    '.zip',
}
MAX_FILE_BYTES = 64 * 1024
MAX_LINES = 400
MAX_LIST = 200
MAX_HITS = 20
MAX_RESULT_CHARS = 8000


class ToolError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def root() -> Path:
    return Path(settings.AGENT_ROOT).resolve()


def _resolve(raw: str) -> Path:
    base = root()
    path = (base / str(raw or '.')).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ToolError('路径超出允许范围。') from exc
    return path


def _blocked(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith('.env') or name in BLOCKED_NAMES:
        return True
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        return True
    return bool(set(part.lower() for part in path.parts) & BLOCKED_DIRS)


def list_dir(path: str = '.') -> str:
    target = _resolve(path)
    if not target.is_dir():
        raise ToolError('不是目录。')
    items = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if _blocked(child):
            continue
        items.append('[dir] ' + child.name if child.is_dir() else '[file] ' + child.name)
        if len(items) >= MAX_LIST:
            items.append('…（还有更多，已截断）')
            break
    return '\n'.join(items) or '（空目录）'


def read_file(path: str) -> str:
    target = _resolve(path)
    if not target.is_file():
        raise ToolError('文件不存在。')
    if _blocked(target):
        raise ToolError('这个文件不允许读取。')
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ToolError(f'文件超过 {MAX_FILE_BYTES // 1024} KiB，太大。')
    try:
        text = target.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        raise ToolError('读取失败。') from exc
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        text = '\n'.join(lines[:MAX_LINES]) + f'\n…（截断，共 {len(lines)} 行）'
    return text


def search(query: str, path: str = '.') -> str:
    keyword = str(query or '').strip()
    if len(keyword) < 2:
        raise ToolError('关键词至少 2 个字。')
    target = _resolve(path)
    hits: list[str] = []
    for item in target.rglob('*'):
        if len(hits) >= MAX_HITS:
            break
        if not item.is_file() or _blocked(item):
            continue
        try:
            if item.stat().st_size > 512 * 1024:
                continue
            text = item.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if keyword.lower() in line.lower():
                hits.append(
                    f'{item.relative_to(root())}:{number}: {line.strip()[:160]}'
                )
                break
    return '\n'.join(hits) or '没有找到匹配内容。'


TOOLS = {
    'list_dir': list_dir,
    'read_file': read_file,
    'search': search,
}
