"""Canned planner output for phase 1.

The real model call lands in phase 1 step 2; this module keeps the
conversation → draft → confirm → tree loop testable without a key.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import Member

DEMO_BADGE = '演示响应：本轮未连接模型'

_LOGIN_WORDS = ('登录', '注册', '账号', '鉴权')
_BOARD_WORDS = ('看板', '任务', '列表')


def _first(members: list[Member], kind: str) -> Member | None:
    return next((member for member in members if member.kind == kind), None)


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _task(ref, parent, title, detail, member, start, end) -> dict:
    return {
        'ref': ref,
        'parent_ref': parent,
        'title': title,
        'detail': detail,
        'assignee_id': member.pk if member else None,
        'start_date': _day(start),
        'end_date': _day(end),
    }


def _without_existing(tasks: list[dict], existing: set[str]) -> list[dict]:
    """Drop tasks already on the tree, and any child of a dropped task."""
    dropped: set[str] = set()
    for item in tasks:
        if item['title'] in existing or item['parent_ref'] in dropped:
            dropped.add(item['ref'])
    return [item for item in tasks if item['ref'] not in dropped]


def _standard(ai: Member | None, human: Member | None, *, board: bool) -> list[dict]:
    tasks = [_task('t1', None, '需求确认', '确认范围、验收标准与时间点', human, 0, 1)]
    tasks += [
        _task('t2', None, '登录模块', '账号密码登录与会话保持', ai, 2, 9),
        _task('t3', 't2', '接口设计', '定义登录、登出、会话校验接口', ai, 2, 5),
        _task('t4', 't2', '页面开发', '登录页、错误提示与跳转', ai, 5, 9),
    ]
    if board:
        tasks.append(_task('t5', None, '任务看板', '横向树视图与节点详情', human, 6, 13))
    return tasks


def _release(human: Member | None, ai: Member | None) -> list[dict]:
    return [
        _task('t6', None, '验收与上线', '过一遍主流程，准备可试用的版本', human, 10, 16),
        _task('t7', 't6', '冒烟测试', '按验收清单跑一遍关键路径', human, 10, 14),
        _task('t8', 't6', '部署上线', '打包、部署、回归', ai, 14, 16),
    ]


def build_draft(project, objective: str) -> dict:
    """Build a deterministic split so the loop can be exercised offline."""
    members = list(project.members.all())
    ai = _first(members, Member.Kind.AI)
    human = _first(members, Member.Kind.HUMAN)
    wants_login = any(word in objective for word in _LOGIN_WORDS)
    wants_board = any(word in objective for word in _BOARD_WORDS)

    existing = set(project.tasks.values_list('title', flat=True))
    drafted = _standard(ai, human, board=wants_board or not wants_login)
    tasks = _without_existing(drafted, existing)
    note = ''
    if not tasks:
        tasks = _without_existing(_release(human, ai), existing)
        note = '你说的这些已经在树上了，我补了一条验收上线的分支。'
    if not tasks:
        return {
            'content': f'{DEMO_BADGE}。这几件事都已经在树上了，我不重复创建。',
            'tasks': [],
        }

    names = {member.pk: member.name for member in members}
    owners = '、'.join(sorted({names.get(item['assignee_id'], '未分配') for item in tasks}))
    content = (
        f'{DEMO_BADGE}。{note or "按你的目标"}拆成 {len(tasks)} 个任务，'
        f'涉及 {owners}。确认后写入任务树，之后可以逐个改负责人和日期。'
    )
    return {'content': content, 'tasks': tasks}
