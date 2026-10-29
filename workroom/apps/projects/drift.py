"""Detect code changes that never made it into the task tree."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from django.utils import timezone

CODE_ROOTS = ('apps', 'templates', 'static')
CODE_SUFFIXES = {'.py', '.html', '.css', '.js'}
IGNORED_PARTS = {'__pycache__', 'migrations', 'node_modules', '.pytest_cache'}
DRIFT_THRESHOLD = timedelta(hours=12)


def latest_code_change(root: Path) -> datetime | None:
    """Newest mtime of source files under the given project root."""
    newest: float = 0.0
    for name in CODE_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob('*'):
            if not path.is_file() or path.suffix not in CODE_SUFFIXES:
                continue
            if IGNORED_PARTS & set(path.parts):
                continue
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    if not newest:
        return None
    return datetime.fromtimestamp(newest, tz=timezone.get_current_timezone())


def hint(project, root: Path, now: datetime | None = None) -> str:
    """Return a one-line reminder when code moved but the tree did not."""
    from django.conf import settings

    if getattr(settings, 'FROZEN', False):
        # 打包后源码是解压出的临时副本，mtime 等于构建时间，比较没有意义。
        return ''
    if not (root / 'apps').is_dir():
        return ''
    moment = now or timezone.now()
    changed = latest_code_change(root)
    if changed is None:
        return ''
    last_task = (
        project.tasks.order_by('-created_at').values_list('created_at', flat=True).first()
    )
    if last_task is not None and last_task >= changed:
        return ''
    gap = moment - changed
    if gap < DRIFT_THRESHOLD:
        return ''
    hours = int(gap.total_seconds() // 3600)
    return (
        f'代码最近有改动（{hours} 小时前），但任务树没有对应节点。'
        '如果这是新做的功能，建议补一条任务，避免下次找不到出处。'
    )
