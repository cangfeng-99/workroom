"""Project library helpers: prompt context, versions and revisions."""

from __future__ import annotations

from django.db.models import F

from .models import LibraryEntry


def prompt_block(project, limit: int = 8, body_chars: int = 1200) -> str:
    """Rules/decisions with their real text, not just titles.

    The project context revision is included so a caller can notice that the
    rules changed after it claimed a task.
    """
    entries = list(
        project.library.filter(
            is_active=True,
            kind__in=[LibraryEntry.Kind.RULE, LibraryEntry.Kind.DECISION],
        ).order_by('-updated_at', '-id')[:limit]
    )
    if not entries:
        return ''
    lines = [
        f'项目资料库（上下文 r{project.context_revision}；规则与已定决策，回答时必须遵守）：'
    ]
    for entry in entries:
        parts = []
        if entry.summary:
            parts.append(entry.summary.strip())
        if entry.body:
            parts.append(entry.body.strip())
        text = '；'.join(part for part in parts if part).replace('\n', ' ')
        if len(text) > body_chars:
            text = text[:body_chars] + '…'
        lines.append(
            f'- [{entry.kind_label} v{entry.version}] {entry.title}'
            + (f'：{text}' if text else '')
        )
    return '\n'.join(lines)


def bump_context(project) -> int:
    project.__class__.objects.filter(pk=project.pk).update(
        context_revision=F('context_revision') + 1
    )
    project.refresh_from_db(fields=['context_revision'])
    return project.context_revision


def tag_list(entry: LibraryEntry) -> list[str]:
    return [tag.strip() for tag in entry.tags.split(',') if tag.strip()]
