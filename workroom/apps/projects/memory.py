"""Project long-term memory stored in the authorized workspace."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import Project


def room(project: Project) -> Path | None:
    raw = (project.workspace_path or '').strip()
    if not raw:
        return None
    root = Path(raw).expanduser()
    return root / '.workroom' if root.is_dir() else None


def read_block(project: Project, limit: int = 6000) -> str:
    base = room(project)
    if base is None:
        return ''
    parts = []
    memo = base / 'MEMORY.md'
    if memo.exists():
        parts.append('长期记忆：' + chr(10) + memo.read_text(encoding='utf-8', errors='replace'))
    daily = base / 'memory' / f'{date.today():%Y-%m-%d}.md'
    if daily.exists():
        parts.append('今日记录：' + chr(10) + daily.read_text(encoding='utf-8', errors='replace'))
    text = (chr(10) + chr(10)).join(parts).strip()
    return text[:limit]


def append(project: Project, text: str, scope: str = 'daily') -> str:
    base = room(project)
    if base is None:
        raise ValueError('还没有授权工作区，先在「工作区与长期记忆」里选择文件夹。')
    value = (text or '').strip()
    if not value:
        raise ValueError('要写入的内容不能为空。')
    (base / 'memory').mkdir(parents=True, exist_ok=True)
    target = base / 'MEMORY.md' if scope == 'long' else base / 'memory' / f'{date.today():%Y-%m-%d}.md'
    if not target.exists():
        target.write_text('# 记忆' + chr(10) + chr(10), encoding='utf-8')
    with target.open('a', encoding='utf-8') as handle:
        handle.write('- ' + value.replace(chr(10), ' ') + chr(10))
    return str(target)
