"""Suggest task owners by matching task type with member roles."""

from __future__ import annotations

from .models import Member, Project

_KINDS = {
    'backend': ('接口', 'api', '数据库', '后端', 'django', '迁移', '鉴权', '权限', '服务端'),
    'frontend': ('页面', '组件', '样式', '前端', 'arkts', '界面', '交互', '布局'),
    'test': ('测试', '验收', '回归', '用例', '检查', '质量'),
    'design': ('设计', '原型', '信息架构', '视觉', '体验'),
    'ops': ('部署', '上线', '服务器', '运维', '监控', '发布'),
    'docs': ('文档', '说明', 'readme', '简报', '手册'),
}

_ROLE_HINTS = {
    'backend': ('后端', '服务端', 'django', 'python', '接口', 'api', '架构'),
    'frontend': ('前端', 'arkts', 'ui', '页面', '鸿蒙', 'harmony'),
    'test': ('测试', 'qa', '质量', '验收'),
    'design': ('设计', '产品', 'ux', '交互'),
    'ops': ('运维', '部署', 'sre', '服务器'),
    'docs': ('产品', '运营', '文档', '写作'),
}


def infer_kind(text: str) -> str | None:
    value = (text or '').lower()
    best = None
    best_hits = 0
    for kind, words in _KINDS.items():
        hits = sum(1 for word in words if word in value)
        if hits > best_hits:
            best, best_hits = kind, hits
    return best


def _score(member: Member, kind: str) -> int:
    text = f'{member.role or ""} {member.persona or ""}'.lower()
    return sum(1 for word in _ROLE_HINTS.get(kind, ()) if word in text)


def pick(project: Project, kind: str | None) -> Member | None:
    if kind is None:
        return None
    members = [
        item
        for item in project.members.filter(is_active=True)
        if item.kind in (Member.Kind.AI, Member.Kind.EXTERNAL)
    ]
    ranked = sorted(
        members,
        key=lambda item: (
            _score(item, kind),
            1 if item.kind == Member.Kind.AI and item.has_key else 0,
            -item.pk,
        ),
        reverse=True,
    )
    if not ranked or _score(ranked[0], kind) == 0:
        return None
    return ranked[0]


def fill(tasks: list[dict], project: Project) -> list[dict]:
    """Fill assignee_id for tasks that don't have one; keep explicit choices."""
    for task in tasks:
        if task.get('assignee_id'):
            continue
        kind = infer_kind(f"{task.get('title', '')} {task.get('detail', '')}")
        member = pick(project, kind)
        if member is not None:
            task['assignee_id'] = member.pk
            task['assignee_hint'] = kind
    return tasks
