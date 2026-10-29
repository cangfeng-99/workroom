"""MCP bridge: project context, claims, deliveries and remote tool calls.

Functions return plain text. ``mcp_server.py`` uses them over stdio (local mode)
or forwards the same tool names to the HTTP bridge (server mode).
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

from django.db import transaction

from . import collaboration, directives, schema_check
from . import delivery as delivery_service
from . import memory as project_memory
from .models import ChatMessage, Delivery, LibraryEntry, Member, Project, ReplyJob, Task
from .permissions import is_server

DEFAULT_TASK_LIMIT = 20
MAX_TASK_LIMIT = 50


class McpError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _project(ref, ctx=None) -> Project:
    text = str(ref or '').strip().lstrip('#')
    queryset = Project.objects.all()
    if ctx is not None:
        queryset = queryset.filter(pk=ctx.project_id)
        if not text:
            return queryset.select_related('owner').get()
    if not text:
        raise McpError('需要 project 参数（项目 id 或名称）。')
    if text.isdigit():
        found = queryset.filter(pk=int(text)).first()
        if found:
            return found
    exact = queryset.filter(name__iexact=text).first()
    if exact:
        return exact
    matches = list(queryset.filter(name__icontains=text)[:2])
    if len(matches) == 1:
        return matches[0]
    raise McpError(f'找不到唯一的项目：{text}')


def _task(project: Project, ref) -> Task:
    text = str(ref or '').strip().lstrip('#')
    if not text:
        raise McpError('需要 task 参数（任务 id 或标题）。')
    if text.isdigit():
        found = project.tasks.filter(pk=int(text)).first()
        if found:
            return found
    exact = project.tasks.filter(title__iexact=text).first()
    if exact:
        return exact
    matches = list(project.tasks.filter(title__icontains=text)[:2])
    if len(matches) == 1:
        return matches[0]
    raise McpError(f'找不到唯一的任务：{text}')


def _entry(project: Project, ref) -> LibraryEntry:
    text = str(ref or '').strip().lstrip('#')
    if not text:
        raise McpError('需要 entry 参数（资料 id 或标题）。')
    if text.isdigit():
        found = project.library.filter(pk=int(text)).first()
        if found:
            return found
    exact = project.library.filter(title__iexact=text).first()
    if exact:
        return exact
    matches = list(project.library.filter(title__icontains=text)[:2])
    if len(matches) == 1:
        return matches[0]
    raise McpError(f'找不到唯一的资料：{text}')


def _parse_date(value, fallback: date) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return fallback


_DUTY_WORDS = {
    'propose': Member.Duty.PROPOSE,
    '提议': Member.Duty.PROPOSE,
    'review': Member.Duty.REVIEW,
    '评审': Member.Duty.REVIEW,
    'decide': Member.Duty.DECIDE,
    '决策': Member.Duty.DECIDE,
    'execute': Member.Duty.EXECUTE,
    '执行': Member.Duty.EXECUTE,
}

_STATUS_WORDS = {
    'todo': Task.Status.TODO,
    '待开始': Task.Status.TODO,
    'doing': Task.Status.DOING,
    '进行中': Task.Status.DOING,
    'done': Task.Status.DONE,
    '已完成': Task.Status.DONE,
    'blocked': Task.Status.BLOCKED,
    '受阻': Task.Status.BLOCKED,
}


def _ctx_member(project: Project, ctx, tool: str = '', name: str = '') -> Member | None:
    if ctx is not None and ctx.member is not None:
        if not ctx.member.is_active or ctx.member.project_id != project.pk:
            raise McpError('令牌绑定的外部成员已失效。')
        return ctx.member
    if ctx is not None:
        raise McpError('执行令牌必须绑定当前项目中的外部工具成员。')
    if str(tool or '').strip():
        found = project.members.filter(
            kind=Member.Kind.EXTERNAL, tool=str(tool).strip(), is_active=True
        ).first()
        if found is not None:
            return found
    if str(name or '').strip():
        found = project.members.filter(
            is_active=True, name__iexact=str(name).strip()
        ).first()
        if found is not None:
            return found
    return None


def list_projects(ctx=None) -> str:
    queryset = Project.objects.all()
    if ctx is not None:
        queryset = queryset.filter(pk=ctx.project_id)
    rows = []
    for project in queryset:
        rows.append(
            f'#{project.pk} {project.name} · 目标 {project.goal_title} · '
            f'{project.percent}%（{project.done_count}/{project.task_count}） · '
            f'上下文 r{project.context_revision}'
        )
    return '\n'.join(rows) or '（还没有项目）'


def get_project(
    project: str,
    ctx=None,
    page: int = 1,
    task_limit: int = DEFAULT_TASK_LIMIT,
    library_limit: int = 10,
) -> str:
    item = _project(project, ctx)
    try:
        page = max(1, int(page or 1))
        task_limit = min(MAX_TASK_LIMIT, max(1, int(task_limit or DEFAULT_TASK_LIMIT)))
        library_limit = min(20, max(1, int(library_limit or 10)))
    except (TypeError, ValueError) as exc:
        raise McpError('分页参数必须是整数。') from exc

    lines = [
        f'项目 #{item.pk} {item.name}',
        f'目标：{item.goal_title}',
        f'上下文版本：r{item.context_revision}',
    ]
    if item.goal_detail:
        lines.append(f'说明：{item.goal_detail}')
    if item.goal_deadline:
        lines.append(f'截止：{item.goal_deadline}')
    lines.append(f'进度：{item.percent}%（{item.done_count}/{item.task_count}）')
    lines.append('边界：任务父子只表示层级，不是依赖图；当前未实现前置依赖调度。')

    team = []
    for member in item.members.filter(is_active=True):
        label = member.get_kind_display()
        if member.role:
            label += f'·{member.role}'
        team.append(f'{member.name}（{label}）')
    if team:
        lines.append('团队：' + '；'.join(team))

    total = item.tasks.count()
    start = (page - 1) * task_limit
    tasks = list(
        item.tasks.select_related('assignee', 'parent').order_by('order', 'pk')[
            start:start + task_limit
        ]
    )
    if tasks:
        lines.append(f'任务（第 {start + 1}-{start + len(tasks)} / 共 {total} 条）：')
        for task in tasks:
            owner = task.assignee.name if task.assignee else '未分配'
            parent = f'（父：{task.parent.title}）' if task.parent_id else ''
            lines.append(
                f'- #{task.pk} {task.title} [{task.get_status_display()}] '
                f'{owner} {task.start_date or "?"}~{task.end_date or "?"}{parent}'
            )
            if task.detail:
                lines.append(f'  内容：{task.detail[:600]}')
            if task.acceptance:
                lines.append(f'  验收：{task.acceptance[:400]}')
        if total > start + len(tasks):
            lines.append(f'（还有 {total - start - len(tasks)} 条，用 page={page + 1} 继续）')
    else:
        lines.append('任务：（无）')

    rules = list(
        item.library.filter(
            is_active=True,
            kind__in=[LibraryEntry.Kind.RULE, LibraryEntry.Kind.DECISION],
        ).order_by('-updated_at', '-id')[:library_limit]
    )
    if rules:
        lines.append(f'规则与决策（正文，最多 {library_limit} 条）：')
        for entry in rules:
            lines.append(
                f'- [{entry.kind_label} v{entry.version}] {entry.title}：'
                f'{(entry.body or entry.summary or "（无正文）")[:1500]}'
            )
    else:
        lines.append('规则与决策：（无）')
    artifacts = list(
        item.library.filter(kind=LibraryEntry.Kind.ARTIFACT).order_by('-id')[:5]
    )
    if artifacts:
        lines.append('产物：' + '；'.join(entry.title for entry in artifacts))

    latest = (
        item.messages.filter(role=ChatMessage.Role.ASSISTANT).order_by('-id').first()
    )
    if latest:
        lines.append(f'最近 AI 输出：{latest.content[:400]}')
    return '\n'.join(lines)


def get_task_context(project: str, task: str, ctx=None) -> str:
    item = _project(project, ctx)
    target = _task(item, task)
    if collaboration.policy_for(item)['require_package']:
        data = collaboration.package_data(target, validate=False)
        run = target.claims.filter(status='active').first()
        data['active_execution'] = dict(run_id=str(run.run_id), package_id=run.package_id,
            context_revision=run.context_revision) if run else None
        return json.dumps(data, ensure_ascii=False)
    lines = [
        f'任务 #{target.pk} {target.title}',
        f'项目：#{item.pk} {item.name}（上下文 r{item.context_revision}）',
        f'状态：{target.get_status_display()}',
        f'负责人：{target.assignee.name if target.assignee else "未分配"}',
        f'时间：{target.start_date or "?"} → {target.end_date or "?"}',
        f'优先级：{target.get_priority_display()}',
        f'内容：{target.detail or "（未填写）"}',
        f'验收条件：{target.acceptance or "（未填写）"}',
        f'父子：{("父 " + target.parent.title) if target.parent_id else "无父任务"}；'
        f'子任务 {target.children.count()} 个（层级，不是依赖）',
    ]
    from .task_explanations import explanation
    readable = explanation(target)
    lines.append(f'当前可做：{readable["label"]}')
    for required in readable['prerequisites']:
        lines.append(f'前置任务：#{required.pk}「{required.title}」· {required.get_status_display()}')
    for blocker in readable['blockers']:
        lines.append(f'需要处理：{blocker["text"]}')
        lines.append(f'怎样继续：{blocker["action"]}')
    rules = list(item.library.filter(is_active=True, kind__in=['rule', 'decision']).order_by('-updated_at', '-pk'))
    if rules:
        lines.append('项目有效规则与决策（适用于所有任务）：')
        for entry in rules[:20]:
            body = entry.body or entry.summary or ''
            lines.append(f'- [#{entry.pk} {entry.kind_label} v{entry.version}] {entry.title}：{body[:4000]}')
            if len(body) > 4000:
                lines.append(f'正文未完，使用 get_library_entry(entry="{entry.pk}") 读取全文。')
        if len(rules) > 20:
            lines.append('其余有效规则请逐条读取 get_library_entry：' + ','.join(str(e.pk) for e in rules[20:]))
    if target.library.filter(is_active=True).exists():
        lines.append('关联资料：')
        for entry in target.library.filter(is_active=True).exclude(kind__in=['rule', 'decision'])[:8]:
            lines.append(
                f'- [{entry.kind_label} v{entry.version}] {entry.title}：'
                f'{(entry.body or entry.summary or "")[:800]}'
            )
    claim_row = target.claims.filter(status='active').first()
    if claim_row:
        lines.append(
            f'当前认领：run {claim_row.run_id} · '
            f'{claim_row.actor_member.name if claim_row.actor_member else "账号"} · '
            f'到期 {claim_row.expires_at:%Y-%m-%d %H:%M}'
        )
    latest = target.deliveries.order_by('-id').first()
    if latest:
        lines.append(
            f'最近交付：#{latest.pk} {latest.get_status_display()} · {latest.summary[:300]}'
        )
        if latest.test_commands:
            lines.append(f'测试：{latest.test_commands[:400]}')
        if latest.test_exit_code is not None:
            lines.append(f'退出码：{latest.test_exit_code}')
    return '\n'.join(lines)


def get_library_entry(project: str, entry: str, ctx=None) -> str:
    item = _project(project, ctx)
    target = _entry(item, entry)
    lines = [
        f'资料 #{target.pk} {target.title}',
        f'类型：{target.kind_label} · v{target.version} · '
        f'{"有效" if target.is_active else "已失效"}',
        f'摘要：{target.summary or "（无）"}',
        f'正文：{target.body or "（无）"}',
    ]
    if target.context:
        lines.append(f'背景：{target.context}')
    if target.options:
        lines.append(f'备选方案：{target.options}')
    if target.conclusion:
        lines.append(f'结论：{target.conclusion}')
    if target.tags:
        lines.append(f'标签：{target.tags}')
    lines.append(f'来源：{target.get_source_display()} {target.source_ref}')
    lines.append(f'项目上下文版本：r{item.context_revision}')
    return '\n'.join(lines)


def list_tasks(project: str, status: str = '', ctx=None) -> str:
    item = _project(project, ctx)
    tasks = item.tasks.select_related('assignee')
    if status:
        wanted = _STATUS_WORDS.get(str(status).strip())
        if wanted is None:
            raise McpError(f'未知状态：{status}')
        tasks = tasks.filter(status=wanted)
    rows = [
        f'#{task.pk} {task.title} [{task.get_status_display()}] '
        f'{task.assignee.name if task.assignee else "未分配"} '
        f'{task.start_date or "?"}~{task.end_date or "?"}'
        for task in tasks
    ]
    return '\n'.join(rows) or '（没有符合条件的任务）'


def create_task(
    project: str,
    title: str,
    detail: str = '',
    assignee: str = '',
    start_date: str = '',
    end_date: str = '',
    acceptance: str = '',
    ctx=None,
) -> str:
    item = _project(project, ctx)
    clean_title = str(title or '').strip()
    if not clean_title:
        raise McpError('title 不能为空。')
    today = date.today()
    start = _parse_date(start_date, today)
    end = _parse_date(end_date, start + timedelta(days=7))
    if end < start:
        raise McpError('结束日期早于开始日期。')

    member = None
    if str(assignee or '').strip():
        member = item.members.filter(
            is_active=True, name__iexact=str(assignee).strip()
        ).first()
        if member is None:
            raise McpError(f'项目里没有成员：{assignee}')

    task = Task.objects.create(
        project=item,
        title=clean_title[:160],
        detail=str(detail or '')[:4000],
        acceptance=str(acceptance or '')[:4000],
        assignee=member,
        start_date=start,
        end_date=end,
        order=item.tasks.count(),
    )
    return f'已创建任务 #{task.pk}「{task.title}」，负责人 {member.name if member else "未分配"}。'


def update_task_status(
    project: str, task: str, status: str, ctx=None, reason: str = '', next_action: str = ''
) -> str:
    item = _project(project, ctx)
    target = _task(item, task)
    wanted = _STATUS_WORDS.get(str(status or '').strip())
    if wanted is None:
        raise McpError(f'未知状态：{status}（可用 todo/doing/done/blocked 或中文）')
    if wanted == Task.Status.DONE:
        if target.status == Task.Status.DONE:
            return f'任务 #{target.pk} 已完成，没有修改验收记录。'
        raise McpError('工具不能代替本人确认完成；请提交交付，再在交付页面核对并确认。')
    if wanted == Task.Status.BLOCKED:
        reason = str(reason or target.blocked_reason).strip()
        next_action = str(next_action or target.unblock_action).strip()
        if not reason or not next_action:
            raise McpError('请提供 reason（卡在哪里）和 next_action（需要谁做什么才能继续）。')
    target.status = wanted
    target.blocked_reason = reason[:8000] if wanted == Task.Status.BLOCKED else ''
    target.unblock_action = next_action[:8000] if wanted == Task.Status.BLOCKED else ''
    target.save(update_fields=['status', 'blocked_reason', 'unblock_action'])
    return f'任务 #{target.pk}「{target.title}」现在是「{target.get_status_display()}」。'


def add_library_entry(
    project: str,
    title: str,
    body: str = '',
    kind: str = 'artifact',
    summary: str = '',
    tags: str = '',
    ctx=None,
) -> str:
    item = _project(project, ctx)
    clean_title = str(title or '').strip()
    if not clean_title:
        raise McpError('title 不能为空。')
    wanted = str(kind or 'artifact').strip()
    if wanted not in dict(LibraryEntry.Kind.choices):
        raise McpError('kind 只能是 rule / artifact / decision。')
    entry = LibraryEntry.objects.create(
        project=item,
        kind=wanted,
        title=clean_title[:160],
        body=str(body or '')[:4000],
        summary=str(summary or '')[:200],
        tags=str(tags or '')[:120],
        source=LibraryEntry.Source.EXTERNAL,
        source_ref='mcp',
    )
    from .library import bump_context

    bump_context(item)
    return f'已写入资料库：{entry.kind_label}「{entry.title}」（上下文 r{item.context_revision}）。'


def next_task(project: str, assignee: str, ctx=None) -> str:
    item = _project(project, ctx)
    name = str(assignee or '').strip()
    if ctx is not None and ctx.member is not None:
        member = ctx.member
    elif name:
        member = item.members.filter(is_active=True, name__iexact=name).first()
    else:
        member = None
    if member is None:
        raise McpError('需要 assignee（成员名称）或绑定外部成员的令牌。')

    task = (
        item.tasks.filter(
            assignee=member,
            status__in=[Task.Status.TODO, Task.Status.DOING],
        )
        .exclude(deliveries__status='pending')
        .order_by('start_date', 'order', 'pk')
        .first()
    )
    if task is None:
        return f'{member.name} 现在没有待办任务。'

    lines = [
        f'任务 {task.pk}：{task.title}',
        f'状态：{task.get_status_display()}',
        f'时间：{task.start_date or "?"} → {task.end_date or "?"}',
        f'优先级：{task.get_priority_display()}',
        f'说明：{task.detail or "（没有填写）"}',
        f'验收条件：{task.acceptance or "（未填写）"}',
        f'上下文版本：r{item.context_revision}',
    ]
    library = list(task.library.all()[:3])
    if library:
        lines.append(
            '关联资料：'
            + '；'.join(
                f'{e.kind_label} v{e.version}:{e.title}' for e in library
            )
        )
    entry = item.library.filter(
        is_active=True, kind__in=[LibraryEntry.Kind.RULE, LibraryEntry.Kind.DECISION]
    ).order_by('-updated_at').first()
    if entry:
        lines.append(f'最新规则：{entry.title} v{entry.version}：{(entry.body or "")[:400]}')
    return '\n'.join(lines)


def claim_task(
    project: str,
    task: str,
    tool: str = '',
    member: str = '',
    ctx=None,
) -> str:
    item = _project(project, ctx)
    target = _task(item, task)
    actor = _ctx_member(item, ctx, tool, member) or (
        target.assignee
        if target.assignee is not None and target.assignee.kind == Member.Kind.EXTERNAL
        else None
    )
    claim_row, created = delivery_service.claim(
        target, member=actor, user=ctx.user if ctx is not None else None
    )
    revision_note = ''
    if claim_row.context_revision != item.context_revision:
        revision_note = (
            f'注意：项目规则已从 r{claim_row.context_revision} 更新到 '
            f'r{item.context_revision}，执行前请重新读取并确认。'
        )
    head = (
        f'已认领任务 #{target.pk}「{target.title}」。'
        if created
        else f'你已持有任务 #{target.pk}「{target.title}」的执行。'
    )
    lines = [
        head,
        f'run：{claim_row.run_id}',
        f'上下文版本：r{claim_row.context_revision}',
        f'任务包快照：#{claim_row.package_id}',
        f'执行到期：{claim_row.expires_at:%Y-%m-%d %H:%M}',
        f'任务说明：{target.detail or "（未填写）"}',
        '开工前先复述：目标一句话 + 验收标准一句话；不复述视为未开工。',
        f'验收条件：{target.acceptance or "（未填写）"}',
    ]
    if target.execution_spec:
        lines.append(
            '执行要求：' + json.dumps(target.execution_spec, ensure_ascii=False)
        )
    if revision_note:
        lines.append(revision_note)
    lines.append('交付时用 submit_result，任务不会由外部工具直接标记完成。')
    if claim_row.package and claim_row.package.snapshot['policy']['require_package']:
        lines.append('本次执行的任务包快照：\n' + json.dumps(claim_row.package.snapshot, ensure_ascii=False))
    return '\n'.join(lines)


def heartbeat_task(project: str, task: str, run_id: str = '', ctx=None) -> str:
    item = _project(project, ctx)
    target = _task(item, task)
    claim_row = (
        target.claims.filter(status='active', run_id=run_id).first()
        if run_id
        else delivery_service.active_claim(
            target,
            member=ctx.member if ctx is not None else None,
            user=ctx.user if ctx is not None else None,
        )
    )
    if claim_row is None:
        raise McpError('没有找到你的执行记录；请先 claim_task。')
    claim_row = delivery_service.heartbeat(
        claim_row,
        member=ctx.member if ctx is not None else None,
        user=ctx.user if ctx is not None else None,
    )
    lines = [
        f'执行 {claim_row.run_id} 心跳已更新，到期 {claim_row.expires_at:%Y-%m-%d %H:%M}。'
    ]
    if claim_row.reconfirm_required:
        lines.append(
            f'规则已变更（认领时 r{claim_row.context_revision}，'
            f'当前 r{item.context_revision}），请重新读取规则后再继续。'
        )
    return '\n'.join(lines)


def release_task(project: str, task: str, ctx=None) -> str:
    item = _project(project, ctx)
    target = _task(item, task)
    member = ctx.member if ctx is not None else None
    user = ctx.user if ctx is not None else None
    with transaction.atomic():
        claim_row = (
            target.claims.select_for_update().filter(status='active').first()
        )
        if claim_row is None:
            raise McpError('没有进行中的认领。')
        same = delivery_service.owns_claim(claim_row, member, user)
        if not same:
            raise McpError('不能释放别人的执行。')
        claim_row.status = 'released'
        claim_row.save(update_fields=['status'])
    return f'已释放任务 #{target.pk} 的认领。'


def submit_result(
    project: str,
    task: str,
    summary: str,
    body: str = '',
    tool: str = '',
    artifact_title: str = '',
    baseline: str = '',
    commit_ref: str = '',
    changed_files: str = '',
    test_commands: str = '',
    test_exit_code=None,
    test_output: str = '',
    evidence_ref: str = '',
    idempotency_key: str = '',
    member: str = '',
    review: bool = False,
    ctx=None,
    accounting=None,
) -> str:
    item = _project(project, ctx)
    target = _task(item, task)
    actor = _ctx_member(item, ctx, tool, member)
    if actor is None and target.assignee is not None:
        actor = target.assignee
    try:
        code = int(test_exit_code) if test_exit_code not in (None, '') else None
    except (TypeError, ValueError) as exc:
        raise McpError('test_exit_code 必须是整数。') from exc
    record, created = delivery_service.submit(
        target,
        summary=summary,
        body=body or (f'产物：{artifact_title}' if artifact_title else ''),
        baseline=baseline,
        commit_ref=commit_ref,
        changed_files=changed_files,
        test_commands=test_commands,
        test_exit_code=code,
        test_output=test_output,
        evidence_ref=evidence_ref,
        idempotency_key=idempotency_key,
        member=actor,
        user=ctx.user if ctx is not None else None,
        require_claim=ctx is not None,
        accounting=accounting,
    )
    if not created:
        return (
            f'这次交付已存在（#{record.pk}，{record.get_status_display()}），'
            '没有重复创建消息、资料或审核。'
        )
    if record.status == Delivery.Status.ACCEPTED:
        return f'交付 #{record.pk} 已存在并通过人工验收，任务已完成。'

    if not is_server():
        return (
            f'已记录「{target.title}」的交付 #{record.pk}，待你确认；'
            '单人模式不自动审核，请在交付页勾选证据后通过，不通过就写原因退回。'
        )

    risk = str((target.execution_spec or {}).get('risk') or 'medium').lower()
    if not review and risk != 'high':
        return (
            f'已记录「{target.title}」的交付 #{record.pk}，等待人工验收。'
            '普通交付不自动审核；需要 AI 复核时显式传 review=true。'
        )

    reviewer = (
        item.members.filter(
            kind=Member.Kind.AI, is_active=True, duty=Member.Duty.REVIEW
        )
        .exclude(key_ciphertext='')
        .order_by('pk')
        .first()
    )
    if reviewer is None:
        reviewer = (
            item.members.filter(kind=Member.Kind.AI, is_active=True)
            .exclude(key_ciphertext='')
            .order_by('pk')
            .first()
        )
    if reviewer is None:
        return (
            f'已记录「{target.title}」的交付 #{record.pk}，等待项目所有者人工验收。'
            '项目里没有可用 AI 审核。'
        )

    from . import queue as job_queue

    job = job_queue.submit(
        item,
        reviewer,
        delivery_service.review_prompt(record),
        ReplyJob.Mode.REVIEW,
        user=ctx.user if ctx is not None else None,
        delivery=record,
    )
    return (
        f'已记录「{target.title}」的交付 #{record.pk}，等待人工验收；'
        f'已交给 {reviewer.name} 给审核建议（job {job.pk}）。AI 意见不会自动通过。'
    )


def ask_project_knowledge(project: str, question: str, ctx=None) -> str:
    from . import rag

    item = _project(project, ctx)
    text = (question or '').strip()
    if not text:
        raise McpError('question 不能为空。')
    result = rag.answer(item, text)
    lines = [result['answer']]
    if result['citations']:
        lines.append('')
        lines.append('引用：')
        for index, citation in enumerate(result['citations'], start=1):
            lines.append(
                f'{index}. 《{citation["title"]}》 相似度 {citation["score"]}'
            )
    if result['mode'] == 'extractive':
        lines.append('')
        lines.append('（服务端未配置对话接口，以上为原文摘录。）')
    return '\n'.join(lines)


def read_memory(project: str, ctx=None) -> str:
    item = _project(project, ctx)
    block = project_memory.read_block(item)
    return block or '还没有授权工作区，或还没有写入记忆。先在「工作区与长期记忆」里授权。'


def append_memory(project: str, text: str, scope: str = "daily", ctx=None) -> str:
    item = _project(project, ctx)
    try:
        path = project_memory.append(item, text, scope=scope)
    except ValueError as exc:
        raise McpError(str(exc)) from exc
    return f'已写入 {path}'


def get_latest_plan(project: str, ctx=None) -> str:
    item = _project(project, ctx)
    messages = item.messages.filter(role=ChatMessage.Role.ASSISTANT).order_by('-id')[:20]
    for message in messages:
        payload = message.payload if isinstance(message.payload, dict) else {}
        if payload.get('source') == 'agent':
            steps = payload.get('steps') or []
            head = '；'.join(
                f'{step.get("tool")} {step.get("args", {}).get("path", "")}'.strip()
                for step in steps[:8]
            )
            return f'{message.content}\n\n（执行步骤：{head}）' if steps else message.content
    return '（这个项目还没有 Agent 计划）'


def list_deliveries(project: str, status: str = '', ctx=None) -> str:
    item = _project(project, ctx)
    queryset = Delivery.objects.filter(task__project=item)
    if status:
        if status not in dict(Delivery.Status.choices):
            raise McpError('status 只能是 pending / accepted / returned。')
        queryset = queryset.filter(status=status)
    rows = [
        f'#{row.pk} task {row.task_id}「{row.task.title}」 [{row.get_status_display()}] '
        f'{row.summary[:160]} · 证据 {row.evidence_ref or "无"}'
        for row in queryset.select_related('task')[:30]
    ]
    return '\n'.join(rows) or '（没有交付）'


def _external_member(project: Project, name: str = '', tool: str = '') -> Member:
    target = None
    if str(name or '').strip():
        target = project.members.filter(
            is_active=True, name__iexact=str(name).strip()
        ).first()
    if target is None and str(tool or '').strip():
        target = project.members.filter(
            is_active=True, kind=Member.Kind.EXTERNAL, tool=str(tool).strip()
        ).first()
    if target is None:
        target = project.members.filter(
            is_active=True, kind=Member.Kind.EXTERNAL
        ).first()
    if target is None:
        raise McpError('项目里没有外部成员。')
    return target


def _stop_control(item: Project, member: Member):
    return (
        item.messages.filter(
            role=ChatMessage.Role.SYSTEM,
            payload__control='stop',
            payload__member=member.pk,
        )
        .order_by('-pk')
        .first()
    )


def _pending_mentions(item: Project, member: Member) -> list:
    pending = []
    for message in item.messages.filter(role=ChatMessage.Role.USER).order_by('-id')[:40]:
        payload = message.payload if isinstance(message.payload, dict) else {}
        if member.pk not in (payload.get('mentions') or []):
            continue
        if item.messages.filter(pk__gt=message.pk, member=member).exists():
            continue
        pending.append(message)
        if len(pending) >= 5:
            break
    return pending


def get_inbox(project: str, assignee: str, ctx=None) -> str:
    item = _project(project, ctx)
    if ctx is not None and ctx.member is not None:
        member = ctx.member
    else:
        member = item.members.filter(
            is_active=True, name__iexact=str(assignee or '').strip()
        ).first()
    if member is None:
        raise McpError(f'项目里没有成员：{assignee}')

    stop = _stop_control(item, member)
    if stop is not None:
        payload = dict(stop.payload or {})
        if not payload.get('consumed'):
            payload['consumed'] = True
            stop.payload = payload
            stop.save(update_fields=['payload'])
            return (
                f'收到停止请求：{member.name} 请立即停止当前工作，'
                '并用 post_message 回报停在哪一步。'
            )

    pending = _pending_mentions(item, member)

    lines = [f'{member.name} 的收件箱']
    if pending:
        lines.append('待回复的 @：')
        for message in reversed(pending):
            snippet = message.content.strip().replace(chr(10), ' ')[:160]
            lines.append(f'- #{message.pk}：{snippet}')
    else:
        lines.append('没有待回复的 @。')

    lines.append('')
    lines.append('下一条待办：')
    lines.append(next_task(project, member.name, ctx=ctx))
    return chr(10).join(lines)


def post_message(
    project: str, content: str, tool: str = '', member: str = '', ctx=None
) -> str:
    item = _project(project, ctx)
    text = str(content or '').strip()
    if not text:
        raise McpError('content 不能为空。')
    target = (
        ctx.member
        if ctx is not None and ctx.member is not None
        else _external_member(item, member, tool)
    )
    text = directives.apply(item, text)
    message = ChatMessage.objects.create(
        project=item,
        member=target,
        role=ChatMessage.Role.ASSISTANT,
        content=text[:8000],
        payload={'source': 'external-chat', 'member': target.pk},
    )
    return f'已以 {target.name} 的身份写入对话（消息 #{message.pk}）。'


def wait_for_work(
    project: str, assignee: str, timeout: int = 20, ctx=None
) -> str:
    """Long-poll the inbox so a client loop can react within seconds.

    The wait condition is a database lookup, not a substring of the inbox text:
    the empty inbox renders 「没有待回复的 @。」, which used to match
    ``'待回复的 @'`` and made this return instantly every single time.
    """
    item = _project(project, ctx)
    if ctx is not None and ctx.member is not None:
        member = ctx.member
    else:
        member = item.members.filter(
            is_active=True, name__iexact=str(assignee or '').strip()
        ).first()
    if member is None:
        raise McpError(f'项目里没有成员：{assignee}')

    deadline = time.monotonic() + max(5, min(int(timeout or 20), 25))
    while True:
        stop = _stop_control(item, member)
        unread_stop = stop is not None and not (stop.payload or {}).get('consumed')
        if unread_stop or _pending_mentions(item, member):
            return get_inbox(project, assignee, ctx=ctx)
        if time.monotonic() >= deadline:
            return '等待超时，暂无新的 @ 或停止请求。'
        time.sleep(1.5)


def report_progress(
    project: str,
    task: str,
    stage: str,
    note: str,
    tool: str = '',
    ctx=None,
) -> str:
    """Post a staged progress line so the project can follow along."""
    item = _project(project, ctx)
    text = str(note or '').strip()
    if not text:
        raise McpError('note 不能为空。')
    labels = {'plan': '计划', 'doing': '进展', 'verify': '验证', 'done': '完成'}
    label = labels.get(str(stage or '').strip().lower(), '进展')
    target = (
        ctx.member
        if ctx is not None and ctx.member is not None
        else _external_member(item, '', tool)
    )
    target_task = _task(item, task) if str(task or '').strip() else None
    message = ChatMessage.objects.create(
        project=item,
        member=target,
        role=ChatMessage.Role.ASSISTANT,
        content=f'【{label}】{text}'[:8000],
        payload={
            'source': 'external-progress',
            'stage': label,
            'task': target_task.pk if target_task else None,
        },
    )
    return f'已记录{label}（#{message.pk}）。'


def whoami(ctx) -> str:
    if ctx is None:
        return '本地 stdio 模式：没有 HTTP 令牌身份。'
    token = ctx.token
    expires = token.expires_at.strftime('%Y-%m-%d %H:%M') if token.expires_at else '长期'
    return (
        f'令牌：{token.name}（{token.get_scope_display()}）\n'
        f'项目：#{token.project_id} {token.project.name}\n'
        f'账号：{token.user.get_username() if token.user else "（无）"}\n'
        f'外部成员：{token.member.name if token.member else "（无）"}\n'
        f'连接实例：{str(token.member.connection_id) if token.member and token.member.connection_id else "旧实例"}\n'
        f'到期：{expires}'
    )


def call_tool(name: str, args: dict | None, ctx=None) -> str:
    """Single entry point: validate the arguments, then run the tool.

    Every caller — stdio, the REST endpoint and the HTTP bridge — arrives here,
    so the contract lives in one place. Validation happens before dispatch so a
    malformed call is reported against the field that is wrong instead of
    surfacing later as "找不到任务" or a raw ValueError.
    """
    if is_server() and ctx is None:
        raise McpError('server 模式必须使用带令牌的远程桥，不能直接读本地库。')
    data, errors, warnings, schema = schema_check.check_tool(name, args or {})
    if errors:
        raise McpError(schema_check.explain(name, errors, warnings, schema))
    text = _dispatch(name, data, ctx)
    if warnings:
        text = f'{text}\n（{"；".join(warnings)}）'
    return text


def _dispatch(name: str, data: dict, ctx=None) -> str:
    if is_server() and ctx is None:
        raise McpError('server 模式必须使用带令牌的远程桥，不能直接读本地库。')
    if name == 'list_projects':
        return list_projects(ctx)
    if name == 'review_delivery':
        item = _project(data.get('project',''), ctx)
        record = Delivery.objects.filter(task__project=item, pk=data.get('delivery')).first()
        if record is None:
            raise McpError('找不到本项目的交付。')
        review = collaboration.review_delivery(record, member=_ctx_member(item, ctx),
            user=ctx.user if ctx else None, verdict=data.get('verdict',''), note=data.get('note',''))
        return f'已记录独立复核 #{review.pk}：{review.verdict}，仍需负责人验收。'
    if name == 'get_project':
        return get_project(
            data.get('project', ''),
            ctx,
            page=data.get('page', 1),
            task_limit=data.get('task_limit', DEFAULT_TASK_LIMIT),
            library_limit=data.get('library_limit', 10),
        )
    if name == 'get_task_context':
        return get_task_context(
            data.get('project', ''), data.get('task', ''), ctx
        )
    if name == 'confirm_task_context':
        item = _project(data.get('project', ''), ctx)
        target = _task(item, data.get('task', ''))
        # ctx 在本地 stdio 模式下是 None，不能直接取 .user
        record = delivery_service.confirm_context(target, int(data.get('revision', 0)),
            member=_ctx_member(item, ctx), user=ctx.user if ctx else None)
        return f'已确认上下文 r{record.context_revision}。'
    if name == 'get_library_entry':
        return get_library_entry(
            data.get('project', ''), data.get('entry', ''), ctx
        )
    if name == 'list_tasks':
        return list_tasks(data.get('project', ''), data.get('status', ''), ctx)
    if name == 'create_task':
        return create_task(
            data.get('project', ''),
            data.get('title', ''),
            data.get('detail', ''),
            data.get('assignee', ''),
            data.get('start_date', ''),
            data.get('end_date', ''),
            data.get('acceptance', ''),
            ctx,
        )
    if name == 'update_task_status':
        return update_task_status(
            data.get('project', ''), data.get('task', ''), data.get('status', ''), ctx,
            reason=data.get('reason', ''), next_action=data.get('next_action', ''),
        )
    if name == 'ask_project_knowledge':
        return ask_project_knowledge(
            data.get('project') or '', data.get('question') or '', ctx
        )

    if name == 'read_memory':
        return read_memory(data.get('project', ''), ctx)
    if name == 'append_memory':
        return append_memory(
            data.get('project', ''), data.get('text', ''), data.get('scope', 'daily'), ctx
        )
    if name == 'add_library_entry':
        return add_library_entry(
            data.get('project', ''),
            data.get('title', ''),
            data.get('body', ''),
            data.get('kind', 'artifact'),
            data.get('summary', ''),
            data.get('tags', ''),
            ctx,
        )
    if name == 'next_task':
        return next_task(
            data.get('project', ''), data.get('assignee', ''), ctx
        )
    if name == 'claim_task':
        return claim_task(
            data.get('project', ''),
            data.get('task', ''),
            data.get('tool', ''),
            data.get('member', ''),
            ctx,
        )
    if name == 'heartbeat_task':
        return heartbeat_task(
            data.get('project', ''),
            data.get('task', ''),
            data.get('run_id', ''),
            ctx,
        )
    if name == 'release_task':
        return release_task(data.get('project', ''), data.get('task', ''), ctx)
    if name == 'submit_result':
        return submit_result(
            data.get('project', ''),
            data.get('task', ''),
            data.get('summary', ''),
            data.get('body', ''),
            data.get('tool', ''),
            data.get('artifact_title', ''),
            data.get('baseline', ''),
            data.get('commit_ref', ''),
            data.get('changed_files', ''),
            data.get('test_commands', ''),
            data.get('test_exit_code'),
            data.get('test_output', ''),
            data.get('evidence_ref', ''),
            data.get('idempotency_key', ''),
            data.get('member', ''),
            bool(data.get('review', False)),
            ctx,
            accounting=data.get('accounting'),
        )
    if name == 'get_latest_plan':
        return get_latest_plan(data.get('project', ''), ctx)
    if name == 'list_deliveries':
        return list_deliveries(
            data.get('project', ''), data.get('status', ''), ctx
        )
    if name == 'get_inbox':
        return get_inbox(
            data.get('project', ''), data.get('assignee', ''), ctx
        )
    if name == 'wait_for_work':
        return wait_for_work(
            data.get('project', ''),
            data.get('assignee', ''),
            int(data.get('timeout') or 20),
            ctx,
        )
    if name == 'report_progress':
        return report_progress(
            data.get('project', ''),
            data.get('task', ''),
            data.get('stage', ''),
            data.get('note', ''),
            data.get('tool', ''),
            ctx,
        )
    if name == 'post_message':
        return post_message(
            data.get('project', ''),
            data.get('content', ''),
            data.get('tool', ''),
            data.get('member', ''),
            ctx,
        )
    if name == 'whoami':
        return whoami(ctx)
    raise McpError(f'未知工具：{name}')
