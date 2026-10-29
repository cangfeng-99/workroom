"""Shared directives emitted by internal AI or external agents.

Supported markers (stripped from the visible message):
  [[memory:...]] / [[memory-long:...]]
  [[task:标题|负责人|YYYY-MM-DD|说明]]
  [[status:任务标题|done]]
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from . import memory
from .models import Project, Task

_MEMORY_RE = re.compile(r'\[\[memory(-long)?:(.+?)\]\]', re.S)
_TASK_RE = re.compile(r'\[\[task:(.+?)\]\]', re.S)
_STATUS_RE = re.compile(r'\[\[status:(.+?)\]\]', re.S)
_DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

MAX_TASKS_PER_REPLY = 3


def _parse_day(text: str):
    """``YYYY-MM-DD`` or nothing. Bad dates are reported, never guessed."""
    if not _DAY_RE.match(text or ''):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None

# 关键词 -> 阶段前缀。新任务按标题自动落到对应阶段，而不是全部塞进开发。
_STAGE_HINTS = (
    ('00', ('立项', '调研', '用户画像', '竞品', '范围')),
    ('10', ('设计', '架构', '方案', '原型', '接口设计', '数据模型')),
    ('20', ('开发', '实现', '编码', '功能', '修复', '重构', '优化', '性能')),
    ('30', ('测试', '验收', '用例', '回归', '兼容', '走查')),
    ('40', ('发布', '打包', '上线', '部署', '文档', '说明', 'readme', '安装包')),
    ('50', ('复盘', '迭代', '总结', '回顾')),
)


def pick_stage(project: Project, title: str):
    """Choose the lifecycle stage a new task belongs to."""
    root = project.tasks.filter(
        parent__isnull=True, title__startswith='10 '
    ).first()
    if root is None:
        return None
    stages = list(root.children.order_by('order'))
    if not stages:
        return root
    lowered = (title or '').lower()
    best: tuple[int, int] | None = None
    chosen = None
    for order, (prefix, words) in enumerate(_STAGE_HINTS):
        stage = next((item for item in stages if item.title.startswith(prefix)), None)
        if stage is None:
            continue
        for word in words:
            position = lowered.find(word.lower())
            if position < 0:
                continue
            # 关键词出现得越靠前越优先；同位置按阶段顺序
            key = (position, order)
            if best is None or key < best:
                best = key
                chosen = stage
    if chosen is not None:
        return chosen
    # 关键词没命中时落到开发阶段，比落到"当前进行中"更可预期
    return next(
        (item for item in stages if item.title.startswith('20')), stages[0]
    )


def apply_with_log(project: Project, text: str) -> tuple[str, list[dict]]:
    """Run directives and return the visible text plus what really happened.

    The returned actions are rendered under the bubble, so "I created a task"
    can be checked against the database instead of trusted.
    """
    value = text or ''
    actions: list[dict] = []
    notices: list[str] = []

    def remember(match):
        scope = 'long' if match.group(1) else 'daily'
        try:
            memory.append(project, match.group(2).strip(), scope=scope)
        except ValueError:
            return ''
        actions.append({
            'kind': 'memory',
            'label': '长期记忆' if scope == 'long' else '今日记录',
        })
        return ''

    cleaned = _MEMORY_RE.sub(remember, value)
    created = 0
    found = list(_TASK_RE.finditer(cleaned))
    for match in found[:MAX_TASKS_PER_REPLY]:
        parts = [item.strip() for item in match.group(1).split('|')]
        title = (parts[0] if parts else '')[:160]
        if not title:
            continue
        if project.tasks.filter(title=title).exists():
            actions.append({
                'kind': 'skip',
                'title': title,
                'label': '同名任务已存在，没有重复创建',
            })
            continue
        stage = pick_stage(project, title)
        owner = None
        if len(parts) > 1 and parts[1]:
            owner = project.members.filter(name__icontains=parts[1]).first()
            if owner is None:
                # 静默丢成 None 会让人以为已经指派了
                actions.append({
                    'kind': 'warn',
                    'title': title,
                    'label': f'没有成员「{parts[1]}」，任务暂时未分配',
                })
        start = None
        if len(parts) > 2 and parts[2]:
            start = _parse_day(parts[2])
            if start is None:
                actions.append({
                    'kind': 'warn',
                    'title': title,
                    'label': f'日期「{parts[2]}」不是 YYYY-MM-DD，没有写入',
                })
        task = Task.objects.create(
            project=project,
            parent=stage,
            title=title,
            status=Task.Status.TODO,
            assignee=owner,
            detail=(parts[3] if len(parts) > 3 else '由对话提出'),
            start_date=start,
            end_date=(start + timedelta(days=7)) if start else None,
        )
        actions.append({
            'kind': 'task',
            'id': task.pk,
            'title': title,
            'label': stage.title if stage else '未分组',
        })
        created += 1
    if len(found) > MAX_TASKS_PER_REPLY:
        actions.append({
            'kind': 'warn',
            'label': f'一次最多建 {MAX_TASKS_PER_REPLY} 条任务，另有 {len(found) - MAX_TASKS_PER_REPLY} 条没处理',
        })
    if created:
        cleaned = _TASK_RE.sub('', cleaned)
    for match in list(_STATUS_RE.finditer(cleaned))[:3]:
        parts = [item.strip() for item in match.group(1).split('|')]
        if len(parts) < 2:
            continue
        task = project.tasks.filter(title__icontains=parts[0]).first()
        if task is None:
            actions.append({
                'kind': 'missing',
                'title': parts[0],
                'label': '没找到这个任务，状态未改',
            })
            continue
        target = parts[1]
        if target not in dict(Task.Status.choices):
            continue
        if target == Task.Status.DONE:
            notices.append(
                f'工具报告「{task.title}」已完成；请提交交付，再由你核对并确认，任务状态没有自动变更。'
            )
            actions.append({
                'kind': 'blocked',
                'title': task.title,
                'label': '状态未改：完成必须走交付验收',
            })
            continue
        task.status = target
        task.save(update_fields=['status'])
        actions.append({
            'kind': 'status',
            'title': task.title,
            'label': dict(Task.Status.choices)[target],
        })
    text_out = '\n\n'.join(
        [part for part in [_STATUS_RE.sub('', cleaned).strip(), *notices] if part]
    )
    return text_out, actions


def apply(project: Project, text: str) -> str:
    cleaned, _ = apply_with_log(project, text)
    return cleaned
