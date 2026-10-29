"""Plain task instructions and evidence-based reasons; never invent a blocker."""
from collections import defaultdict

from .models import Task


def validate_prerequisites(task, prerequisites):
    from .delivery import DeliveryError
    chosen = list(prerequisites)
    if any(row.project_id != task.project_id for row in chosen):
        raise DeliveryError('前置任务必须来自同一个项目。')
    graph = {row.pk: {p.pk for p in row.prerequisites.all()}
             for row in task.project.tasks.prefetch_related('prerequisites')}
    graph[task.pk] = {row.pk for row in chosen}
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise DeliveryError('前置关系不能绕回自己；请取消形成循环的那一项。')
        if key in visited:
            return
        visiting.add(key)
        for other in graph.get(key, ()):
            visit(other)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
    return chosen


def explanation(task, children=None, latest_delivery=None):
    guide = task.guide if isinstance(task.guide, dict) else {}
    who = task.assignee.name if task.assignee else '负责人'
    prerequisites = list(task.prerequisites.all())
    pending = [p for p in prerequisites if p.status != Task.Status.DONE]
    blockers = []
    if task.status != Task.Status.DONE:
        if task.blocked_reason.strip():
            blockers.append(dict(kind='recorded', text=task.blocked_reason.strip(),
                                 action=task.unblock_action.strip() or f'请{who}说明需要谁做什么，才能继续。'))
        for row in pending:
            actor = row.assignee.name if row.assignee else '负责人'
            blockers.append(dict(kind='prerequisite', task_id=row.pk, title=row.title,
                                 text=f'先完成 #{row.pk}「{row.title}」，目前是{row.get_status_display()}。',
                                 action=f'由{actor}先完成这一步，再检查当前任务是否可以开始。'))
    if latest_delivery is None:
        records = list(task.deliveries.all())
        latest_delivery = max(records, key=lambda row: row.pk) if records else None
    children = list(task.children.all()) if children is None else children
    label = task.get_status_display()
    if task.status == Task.Status.DONE:
        label = '已完成'
    elif latest_delivery and latest_delivery.status == 'pending':
        label = '等负责人验收'
        if not task.blocked_reason.strip():
            blockers = [dict(kind='acceptance', delivery_id=latest_delivery.pk,
                             text=f'已经提交交付 #{latest_delivery.pk}，还没有由负责人确认通过。',
                             action='负责人打开交付记录，核对结果后通过或退回。')]
    elif latest_delivery and latest_delivery.status == 'returned':
        label = '待修改'
        blockers.append(dict(kind='returned', text='上次交付被退回：' + latest_delivery.review_note,
                             action=f'由{who}按退回意见修改，再提交一份新的交付。'))
    elif task.blocked_reason.strip():
        label = '受阻'
    elif pending:
        label = '等前置任务'
    elif children and task.status == Task.Status.BLOCKED:
        count = sum(row.status != Task.Status.DONE for row in children)
        label = '等子任务完成' if count else '等阶段确认'
        blockers.append(dict(kind='children', text=f'下面还有 {count} 项任务未完成。' if count else '下面的任务已完成，这个阶段还没确认结束。',
                             action='展开下面的任务，先处理前置条件已满足的一项。' if count else '请负责人确认这个阶段的结果。'))
    elif guide.get('planning') and task.status == Task.Status.BLOCKED:
        label = '待准备'
        blockers.append(dict(kind='preparation', text='这是一项后续计划，还没有安排本次开工。',
                             action=f'请负责人确认要做的内容，再把任务交给{who}。'))
    elif task.status == Task.Status.BLOCKED:
        label = '原因待补充'
        blockers.append(dict(kind='unknown', text='任务被标为受阻，但还没有填写具体原因。',
                             action='请负责人补充卡在哪里、需要谁处理，以及处理后怎样继续。'))
    spec = task.execution_spec if isinstance(task.execution_spec, dict) else {}
    if (task.status != Task.Status.DONE and not children and not latest_delivery
            and task.project.policy.get('require_package') and spec.get('work_kind', 'code') == 'code'):
        missing = []
        if not task.detail.strip():
            missing.append('具体工作内容')
        if not task.acceptance.strip():
            missing.append('怎样才算完成')
        if not spec.get('baseline'):
            missing.append('本次使用的代码版本')
        if not spec.get('allowed_paths'):
            missing.append('这次允许修改哪些文件')
        if not spec.get('check_commands'):
            missing.append('完成后运行什么检查')
        if missing:
            blockers.append(dict(kind='package', text='开工前还要确认：' + '、'.join(missing) + '。',
                                 action='由负责人核对项目文件夹并补齐任务包；这不是程序运行报错。'))
            if label == Task.Status.TODO.label:
                label = '待准备'
    summary = str(guide.get('summary') or '').strip()
    if not summary:
        lines = [line.strip() for line in task.detail.splitlines() if line.strip()]
        summary = next((line for line in lines if not line.startswith(('【', '计划编号', 'PLAN-'))), '')
        if len(summary) > 180:
            summary = '工作内容较长，展开下面的说明可完整阅读。'
        if not summary:
            summary = '还没有说明这项任务具体要交付什么。'
    tone = 'waiting' if blockers and not task.blocked_reason and label != '原因待补充' else task.status
    return dict(label=label, tone=tone, summary=summary, blockers=blockers, primary=blockers[0] if blockers else None,
                next_action=(blockers[0]['action'] if blockers else
                             ('结果已记录，可查看验收证据。' if task.is_done else f'由{who}按下面的步骤完成后提交结果。')),
                owner=who,
                owner_short=(task.assignee.short_name if task.assignee else who),
                guide=guide, prerequisites=prerequisites)


def prepare(tasks, focus_id=None):
    children = defaultdict(list)
    for task in tasks:
        children[task.parent_id].append(task)
    for task in tasks:
        task.readable = explanation(task, children=children[task.pk])
    focus_path = set()
    by_id = {task.pk: task for task in tasks}
    node = by_id.get(focus_id)
    while node and node.pk not in focus_path:
        focus_path.add(node.pk)
        node = by_id.get(node.parent_id)

    def branch(task, depth, first):
        return dict(task=task, children=[branch(child, depth + 1, first and i == 0)
                                         for i, child in enumerate(children[task.pk])],
                    opened=(task.pk in focus_path or (first and depth < 3)), depth=depth)
    return [branch(task, 0, i == 0) for i, task in enumerate(children[None])]


def ensure_claimable(task):
    from .delivery import DeliveryError
    state = explanation(task)
    latest = next((row for row in task.deliveries.all() if row.status == 'pending'), None)
    if latest:
        raise DeliveryError(f'交付 #{latest.pk} 正在等负责人验收，请先处理交付，不要重复执行。')
    dependencies = [b for b in state['blockers'] if b['kind'] == 'prerequisite']
    if dependencies:
        raise DeliveryError(dependencies[0]['text'] + dependencies[0]['action'])
    if task.status == Task.Status.BLOCKED:
        raise DeliveryError(state['primary']['text'] + state['next_action'])
