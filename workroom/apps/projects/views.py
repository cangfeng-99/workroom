"""Phase-1 views: project list, project space, chat, draft confirm, task status."""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import (
    agent,
    agent_tools,
    ai_client,
    assignment,
    chain,
    collaboration,
    crypto,
    demo,
    drift,
    library,
    mcp_clients,
    memory,
    personas,
    planner,
    providers,
    rag,
    rollup,
    user_profile,
    web_search,
)
from . import (
    queue as job_queue,
)
from .forms import ExternalMemberForm, MemberConfigForm, NewMemberForm
from .models import (
    ChatMessage,
    Delivery,
    LibraryEntry,
    Member,
    Project,
    ProjectMembership,
    ReplyJob,
    Task,
    UserProfile,
)
from .permissions import audit, is_server, project_for, role_of, visible_projects
from .tree import NODE_HEIGHT, NODE_WIDTH, build_tree

TABS = ('chat', 'tasks', 'library', 'progress')
PRODUCT_DEFINITION_TAG = 'product-definition'
RISK_LABELS = {'low': '低', 'normal': '普通', 'high': '高'}
WORK_KIND_LABELS = {'code': '代码', 'general': '通用'}


def _mention_candidates(members) -> list[dict]:
    """Every active project member can be mentioned; the client only inserts text."""
    items = []
    for member in members:
        if member.kind == Member.Kind.EXTERNAL:
            detail = member.tool or member.role or '外部工具'
        elif member.kind == Member.Kind.AI:
            detail = member.role or member.model_name or 'AI'
        else:
            detail = member.role or '成员'
        items.append(
            {
                'id': member.pk,
                'name': member.name,
                'kind': member.kind,
                'kindLabel': member.get_kind_display(),
                'role': member.role or '',
                'detail': detail,
                'initial': member.initial,
            }
        )
    return items


def _execution_preview(task) -> dict:
    """Read the stored package without re-validating legacy task data."""
    raw = task.execution_spec if isinstance(task.execution_spec, dict) else {}

    def as_list(value):
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [line.strip() for line in str(value or '').splitlines() if line.strip()]

    work_kind = str(raw.get('work_kind') or '')
    risk = str(raw.get('risk') or '')
    return {
        'configured': bool(raw),
        'work_kind': work_kind,
        'work_kind_label': WORK_KIND_LABELS.get(work_kind, work_kind or '—'),
        'workspace_key': str(raw.get('workspace_key') or ''),
        'baseline': str(raw.get('baseline') or ''),
        'risk': risk,
        'risk_label': RISK_LABELS.get(risk, risk or '—'),
        'allowed_paths': as_list(raw.get('allowed_paths')),
        'relevant_files': as_list(raw.get('relevant_files')),
        'check_commands': as_list(raw.get('check_commands')),
    }


def _product_definition(library_entries):
    """The newest active artifact tagged product-definition for this project."""
    for item in library_entries:
        if item.kind != LibraryEntry.Kind.ARTIFACT or not item.is_active:
            continue
        if PRODUCT_DEFINITION_TAG in [tag.lower() for tag in item.tag_list]:
            return item
    return None


def _space_url(
    project: Project,
    *,
    tab: str | None = None,
    task: Task | None = None,
    entry: LibraryEntry | None = None,
) -> str:
    url = reverse('projects:space', args=[project.pk])
    params = {}
    if tab:
        params['tab'] = tab
    if task is not None:
        params['task'] = task.pk
    if entry is not None:
        params['entry'] = entry.pk
    return f'{url}?{urlencode(params)}' if params else url


def _member_base_url(member: Member) -> str:
    preset = providers.get(member.provider)
    if member.provider == providers.CUSTOM or preset is None:
        return member.base_url
    return preset['base_url']


def _start_job(
    project: Project, member: Member | None, text: str, mode: str, user=None
) -> ReplyJob:
    """Queue a model job.

    Local mode keeps the historical daemon thread. Server mode only writes a
    queued row; ``manage.py workroom_worker`` is the only executor.
    """
    return job_queue.submit(project, member, text, mode, user=user)


_PROMPT_FIELDS = ('role', 'task', 'context', 'goal', 'constraints', 'output', 'acceptance')


def _apply_memory(project: Project, text: str) -> str:
    from . import directives

    return directives.apply(project, text)


def _decision_ready(text: str) -> bool:
    """Require a five-part decision; '无 dissent + 高 confidence' is suspicious."""
    if not text or '仍需讨论' in text:
        return False
    for key in ('结论', '依据', '反方意见', '未解决', '置信度'):
        if key not in text:
            return False
    dissent = re.search(r'反方意见[：:]\s*(.+)', text)
    confidence = re.search(r'置信度[：:]\s*(.+)', text)
    value = dissent.group(1).strip() if dissent else ''
    level = confidence.group(1).strip() if confidence else ''
    if value in {'无', '没有', '暂无', '无。', '没有。'} and '高' in level:
        return False
    return True


def _stage_status(stage: Task, items: list[Task]) -> str:
    """Derive stage status from its children so the header never drifts."""
    return rollup.fold(
        [item.status for item in items],
        stage.status,
        rollup.is_blocked_on_purpose(stage),
    )


def _clean_reasoning(text: str) -> str:
    """Drop provider-encoded/compressed reasoning that renders as garbage."""
    value = (text or '').strip()
    if not value:
        return ''
    sample = value[:6000]
    letters = sum(
        1 for ch in sample if ch.isalpha() or '一' <= ch <= '鿿'
    )
    if len(sample) > 200 and letters / len(sample) < 0.25:
        return ''
    cleaned = ''.join(
        ch for ch in sample if ch in chr(10) + chr(9) or ch.isprintable()
    )
    return cleaned[:8000]


def _earlier_prompt_drafts(project: Project, original: str) -> list[ChatMessage]:
    """Drafts for the same original wording, oldest first."""
    found: list[ChatMessage] = []
    for message in ChatMessage.objects.filter(
        project=project, role=ChatMessage.Role.ASSISTANT
    ).only('id', 'payload'):
        data = message.payload if isinstance(message.payload, dict) else {}
        if data.get('source') != 'prompt-draft':
            continue
        if (data.get('prompt_original') or '').strip() == original:
            found.append(message)
    return found


def _supersede_draft(message: ChatMessage) -> None:
    payload = message.payload if isinstance(message.payload, dict) else {}
    if payload.get('prompt_superseded'):
        return
    payload['prompt_superseded'] = True
    message.payload = payload
    message.save(update_fields=['payload'])


def _prompt_original_from_history(project: Project, message: ChatMessage) -> str:
    """Fall back to the user message that spawned this draft."""
    prior = (
        ChatMessage.objects.filter(
            project=project, role=ChatMessage.Role.USER, pk__lt=message.pk
        )
        .order_by('-pk')
        .first()
    )
    if prior is None:
        return ''
    return prior.content.removeprefix('【提示词】').strip()


def _run_prompt_draft(job: ReplyJob) -> None:
    member = job.member
    project = job.project
    if member is None:
        raise crypto.CryptoError('成员已被删除。')
    original = job.prompt.removeprefix('【提示词】').strip()
    context = project.goal_title + (
        f'：{project.goal_detail}' if project.goal_detail else ''
    )
    identity = user_profile.for_project(project)
    raw = ai_client.complete_json(
        base_url=_member_base_url(member),
        model=member.model_name,
        api_key=crypto.unprotect(member.key_ciphertext),
        messages=ai_client.prompt_draft_messages(
            original,
            context,
            identity.get_role_display() if identity else '',
        ),
    )
    data = {key: str(raw.get(key) or '').strip()[:2000] for key in _PROMPT_FIELDS}
    if not data['task']:
        raise ai_client.PlannerClientError('提示词草案缺少任务描述。')
    earlier = _earlier_prompt_drafts(project, original)
    payload = {
        'source': 'prompt-draft',
        'prompt_draft': data,
        'prompt_original': original,
        'prompt_version': len(earlier) + 1,
    }
    if earlier:
        payload['regenerate_from'] = earlier[-1].pk
        _supersede_draft(earlier[-1])
    ChatMessage.objects.create(
        project=project,
        member=member,
        role=ChatMessage.Role.ASSISTANT,
        content='我理解的需求如下，请确认或修改，确认后我按这份提示词开始：',
        payload=payload,
    )


def _run_one(job: ReplyJob) -> tuple[str, dict]:
    """Run the model call for one job and return (content, payload)."""
    project = job.project
    member = job.member
    if member is None:
        raise crypto.CryptoError('成员已被删除。')
    context = project.goal_title + (
        f'：{project.goal_detail}' if project.goal_detail else ''
    )
    library_block = library.prompt_block(project)
    if library_block:
        context = context + chr(10) + chr(10) + library_block
    identity_block = user_profile.prompt_block(project)
    if identity_block:
        context = context + chr(10) + chr(10) + identity_block
    memory_block = memory.read_block(project)
    if memory_block:
        context = context + chr(10) + chr(10) + '项目长期记忆：' + chr(10) + memory_block
    context = context + chr(10) + chr(10) + (
        '需要写入记忆时，输出 [[memory:内容]]（长期用 [[memory-long:内容]]）；'
        '新增任务输出 [[task:标题|负责人|YYYY-MM-DD|说明]]；'
        '更新状态输出 [[status:任务标题|done]]。只写真实发生的，不要解释标记。'
    )

    if job.mode == ReplyJob.Mode.PLAN:
        start, end = planner.window(project)
        members = list(project.members.filter(is_active=True))
        raw = ai_client.fetch_plan(
            base_url=_member_base_url(member),
            model=member.model_name,
            api_key=crypto.unprotect(member.key_ciphertext),
            objective=job.prompt,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            instructions=(chr(10) + chr(10)).join(
                part for part in (project.goal_detail, library_block) if part
            ),
            members=[
                {
                    'id': item.pk,
                    'name': item.name,
                    'kind': item.kind,
                    'role': item.role,
                    'persona': item.persona,
                }
                for item in members
            ],
        )
        tasks = assignment.fill(planner.validate(raw, members, start, end), project)
        return (
            f'{member.name} 拆成 {len(tasks)} 个任务，确认后写入任务树。',
            {'tasks': tasks, 'source': 'model'},
        )

    answer = ai_client.fetch_reply(
        base_url=_member_base_url(member),
        model=member.model_name,
        api_key=crypto.unprotect(member.key_ciphertext),
        message=job.prompt,
        project_context=context,
        member={
            'name': member.name,
            'role': member.role,
            'persona': member.persona,
        },
    )
    return (
        answer['text'],
        {
            'source': 'chat',
            'reasoning': _clean_reasoning(answer['reasoning']),
            'reasoning_source': answer['reasoning_source'],
        },
    )


def _member_label(member: Member) -> str:
    return (
        f'{member.name}（{member.provider or "未配置"} / '
        f'{member.model_name or "未填模型"}）'
    )


def _job_message(job, **values):
    with transaction.atomic():
        job_queue.ensure_active(job.pk)
        return ChatMessage.objects.create(**values)


def _save_progress(job_id: int, answer: str, reasoning: str, phase: str) -> None:
    changed = job_queue.update_active(job_id,
        partial_answer=answer[-8000:],
        partial_reasoning=reasoning[-8000:],
        phase=phase,
    )
    if not changed:
        raise job_queue.JobStopped()


def _stream_one(job: ReplyJob) -> dict | None:
    """Consume the model stream, writing progress; None means cancelled."""
    member = job.member
    project = job.project
    if member is None:
        raise crypto.CryptoError('成员已被删除。')
    context = project.goal_title + (
        f'：{project.goal_detail}' if project.goal_detail else ''
    )
    library_block = library.prompt_block(project)
    if library_block:
        context = context + chr(10) + chr(10) + library_block
    identity_block = user_profile.prompt_block(project)
    if identity_block:
        context = context + chr(10) + chr(10) + identity_block
    memory_block = memory.read_block(project)
    if memory_block:
        context = context + chr(10) + chr(10) + '项目长期记忆：' + chr(10) + memory_block
    context = context + chr(10) + chr(10) + (
        '需要写入记忆时，输出 [[memory:内容]]（长期用 [[memory-long:内容]]）；'
        '新增任务输出 [[task:标题|负责人|YYYY-MM-DD|说明]]；'
        '更新状态输出 [[status:任务标题|done]]。只写真实发生的，不要解释标记。'
    )
    answer_parts: list[str] = []
    reasoning_parts: list[str] = []
    last_save = 0.0
    last_check = 0.0
    _save_progress(job.pk, '', '', 'connecting')

    for kind, chunk in ai_client.stream_reply(
        base_url=_member_base_url(member),
        model=member.model_name,
        api_key=crypto.unprotect(member.key_ciphertext),
        message=job.prompt,
        project_context=context,
        member={
            'name': member.name,
            'role': member.role,
            'persona': member.persona,
        },
    ):
        if kind == 'reasoning':
            reasoning_parts.append(chunk)
        else:
            answer_parts.append(chunk)

        now = time.monotonic()
        if now - last_save > 0.5:
            phase = 'answering' if answer_parts else 'thinking'
            _save_progress(
                job.pk, ''.join(answer_parts), ''.join(reasoning_parts), phase
            )
            last_save = now
        if now - last_check > 1.0:
            last_check = now
            if (not job_queue.active(job.pk)):
                return None

    return ai_client.split_reply(
        ''.join(answer_parts).strip(), ''.join(reasoning_parts)
    )


def _discussion_plan(project: Project) -> tuple[list[Member], list[Member], Member]:
    participants = [
        member
        for member in project.members.filter(is_active=True)
        if member.kind == Member.Kind.AI and member.has_key
    ]
    if not participants:
        raise crypto.CryptoError('没有可用的 AI 成员。')
    decider = next(
        (m for m in participants if m.duty == Member.Duty.DECIDE), participants[-1]
    )
    proposers = [
        m
        for m in participants
        if m.duty == Member.Duty.PROPOSE and m.pk != decider.pk
    ]
    if not proposers:
        proposers = [m for m in participants if m.pk != decider.pk] or [decider]
    reviewers = [
        m for m in participants if m.duty == Member.Duty.REVIEW and m.pk != decider.pk
    ]
    return proposers, reviewers, decider


def _run_discussion(job: ReplyJob) -> None:
    """One proposal round, one review round, then a decision — each message saved."""
    project = job.project
    proposers, reviewers, decider = _discussion_plan(project)
    participants = [
        m
        for m in project.members.filter(is_active=True)
        if m.kind == Member.Kind.AI and m.has_key
    ]
    if len(participants) == 1:
        proposers, reviewers = [], []
    context = project.goal_title + (
        f'：{project.goal_detail}' if project.goal_detail else ''
    )
    identity_block = user_profile.prompt_block(project)
    if identity_block:
        context = context + chr(10) + chr(10) + identity_block
    memory_block = memory.read_block(project)
    if memory_block:
        context = context + chr(10) + chr(10) + '项目长期记忆：' + chr(10) + memory_block
    context = context + chr(10) + chr(10) + (
        '需要写入记忆时，输出 [[memory:内容]]（长期用 [[memory-long:内容]]）；'
        '新增任务输出 [[task:标题|负责人|YYYY-MM-DD|说明]]；'
        '更新状态输出 [[status:任务标题|done]]。只写真实发生的，不要解释标记。'
    )
    transcript: list[str] = []
    spoken: list[Member] = []
    kickoff = job.prompt.startswith('【立项会】')
    research = (
        web_search.research_block(job.prompt.removeprefix('【立项会】'))
        if kickoff
        else ''
    )

    externals = list(
        project.members.filter(is_active=True, kind=Member.Kind.EXTERNAL)
    )
    if externals:
        names = '、'.join(member.name for member in externals)
        ChatMessage.objects.create(
            project=project,
            role=ChatMessage.Role.USER,
            content=(
                f'@{names} 请参与本轮讨论：{job.prompt}' + chr(10)
                + '给出你的判断、风险和你能做/不能做的部分，回复会追加到讨论里。'
            ),
            payload={
                'mentions': [member.pk for member in externals],
                'source': 'discuss-invite',
            },
        )

    def speak(phase: str, member: Member, label: str) -> str | None:
        _save_progress(job.pk, '\n\n'.join(transcript), '', phase)
        parts: list[str] = []
        reason_parts: list[str] = []
        last_save = 0.0
        last_check = 0.0
        messages = ai_client.discussion_messages(
            phase=phase,
            member={
                'name': member.name,
                'role': member.role,
                'persona': member.persona,
            },
            user_message=job.prompt,
            project_context=context,
            transcript='\n\n'.join(transcript),
            kickoff=kickoff,
            research=research,
        )
        try:
            for kind, chunk in ai_client.stream_messages(
                base_url=_member_base_url(member),
                model=member.model_name,
                api_key=crypto.unprotect(member.key_ciphertext),
                messages=messages,
            ):
                if kind == 'content':
                    parts.append(chunk)
                elif kind == 'reasoning':
                    reason_parts.append(chunk)
                now = time.monotonic()
                if now - last_save > 0.5:
                    draft = '\n\n'.join(
                        transcript + [f'【{label} · {member.name}】\n' + ''.join(parts)]
                    )
                    _save_progress(job.pk, draft, _clean_reasoning(''.join(reason_parts)), phase)
                    last_save = now
                if now - last_check > 1.0:
                    last_check = now
                    if (not job_queue.active(job.pk)):
                        return None
        except (
            crypto.CryptoError,
            ai_client.PlannerClientError,
            planner.PlanError,
        ) as exc:
            reason = getattr(exc, 'message', '') or '未知错误'
            _job_message(job,
                project_id=job.project_id,
                member_id=member.pk,
                role=ChatMessage.Role.ASSISTANT,
                content=f'{_member_label(member)}没答上来：{reason}',
                payload={'source': 'error', 'phase': phase},
            )
            transcript.append(f'【{label} · {member.name}】\n（没答上来：{reason}）')
            return None

        text = ''.join(parts).strip()
        if not text:
            return None
        spoken.append(member)
        from . import directives

        text, actions = directives.apply_with_log(job.project, text)
        payload = {
            'source': 'discuss',
            'phase': phase,
            'reasoning': _clean_reasoning(''.join(reason_parts)),
            'reasoning_source': 'model',
        }
        if actions:
            payload['actions'] = actions
        _job_message(job,
            project_id=job.project_id,
            member_id=member.pk,
            role=ChatMessage.Role.ASSISTANT,
            content=text,
            payload=payload,
        )
        transcript.append(f'【{label} · {member.name}】\n{text}')
        _save_progress(job.pk, '\n\n'.join(transcript), '', phase)
        return text

    max_rounds = 1 if len(participants) == 1 else 5
    for round_no in range(1, max_rounds + 1):
        if round_no == 1:
            for member in proposers:
                if speak('proposal', member, '提议') is None:
                    return
        for member in reviewers:
            if speak('review', member, '评审') is None:
                return
        decision_text = speak('decision', decider, '决策')
        if decision_text is None:
            return
        if _decision_ready(decision_text):
            break
        if round_no < max_rounds:
            transcript.append(
                f'【主持人】第 {round_no} 轮未收敛，进入第 {round_no + 1} 轮。'
            )
            _save_progress(job.pk, chr(10).join(transcript), '', 'review')
    if spoken:
        drafter = decider if spoken[-1] == decider else spoken[-1]
        _attach_discussion_draft(job, drafter, transcript)


_DUTY_WORDS = {
    '决策': Member.Duty.DECIDE,
    '拍板': Member.Duty.DECIDE,
    '评审': Member.Duty.REVIEW,
    '审核': Member.Duty.REVIEW,
    '提议': Member.Duty.PROPOSE,
    '出主意': Member.Duty.PROPOSE,
    '执行': Member.Duty.EXECUTE,
}


def _extract_mentions(project: Project, text: str) -> list[Member]:
    """Return non-human members mentioned as @Name, longest name first."""
    folded = text.lower()
    found = []
    members = project.members.filter(is_active=True).exclude(
        kind=Member.Kind.HUMAN
    )
    for member in sorted(members, key=lambda item: len(item.name), reverse=True):
        names = [member.name]
        if member.kind == Member.Kind.EXTERNAL and member.tool:
            names.append(member.tool)
        parts = [part.strip() for part in member.name.split('·') if part.strip()]
        names.extend(parts)
        if any(f'@{name}'.lower() in folded for name in names):
            found.append(member)
    return found


def _match_member(project: Project, raw: str) -> Member | None:
    name = raw.strip().strip('“”"\'，。, .')
    if not name:
        return None
    exact = list(project.members.filter(is_active=True, name__iexact=name))
    if len(exact) == 1:
        return exact[0]
    fuzzy = list(project.members.filter(is_active=True, name__icontains=name))
    return fuzzy[0] if len(fuzzy) == 1 else None


def _handle_team_command(project: Project, text: str) -> bool:
    """Handle "swap identities" style requests without calling a model."""
    compact = text.strip()

    match = re.match(
        r'^把\s*(.+?)\s*(?:和|与)\s*(.+?)\s*的?\s*身份\s*(?:互换|交换)', compact
    )
    if match:
        first = _match_member(project, match.group(1))
        second = _match_member(project, match.group(2))
        if (
            first
            and second
            and first.pk != second.pk
            and first.kind == Member.Kind.AI
            and second.kind == Member.Kind.AI
        ):
            first.role, second.role = second.role, first.role
            first.duty, second.duty = second.duty, first.duty
            first.persona, second.persona = second.persona, first.persona
            first.save(update_fields=['role', 'duty', 'persona'])
            second.save(update_fields=['role', 'duty', 'persona'])
            ChatMessage.objects.create(
                project=project,
                role=ChatMessage.Role.SYSTEM,
                content=f'已互换 {first.name} 和 {second.name} 的身份与职责。',
            )
            return True

    match = re.match(
        r'^让\s*(.+?)\s*(?:来|去)?\s*(?:做|担任|负责|当)\s*'
        r'(决策|拍板|评审|审核|提议|出主意|执行)',
        compact,
    )
    if match:
        member = _match_member(project, match.group(1))
        if member:
            member.duty = _DUTY_WORDS[match.group(2)]
            member.save(update_fields=['duty'])
            ChatMessage.objects.create(
                project=project,
                role=ChatMessage.Role.SYSTEM,
                content=f'已把 {member.name} 的讨论职责改为「{member.get_duty_display()}」。',
            )
            return True

    match = re.match(r'^把\s*(.+?)\s*(?:改名|改叫|名字改成|改名为)\s*(.+)$', compact)
    if match:
        member = _match_member(project, match.group(1))
        new_name = match.group(2).strip().strip('“”"\'。')
        if member and new_name:
            old_name = member.name
            member.name = new_name[:80]
            member.save(update_fields=['name'])
            ChatMessage.objects.create(
                project=project,
                role=ChatMessage.Role.SYSTEM,
                content=f'已把 {old_name} 改名为 {member.name}。',
            )
            return True

    return False


def _run_identity(job: ReplyJob) -> None:
    """A newly added AI introduces itself and defines its own role."""
    member = job.member
    project = job.project
    if member is None:
        raise crypto.CryptoError('成员已被删除。')
    context = project.goal_title + (
        f'：{project.goal_detail}' if project.goal_detail else ''
    )
    library_block = library.prompt_block(project)
    if library_block:
        context = context + chr(10) + chr(10) + library_block
    roster = [
        {
            'name': item.name,
            'role': item.role,
            'duty': item.get_duty_display(),
        }
        for item in project.members.filter(kind=Member.Kind.AI, is_active=True).exclude(pk=member.pk)
    ]
    try:
        data = ai_client.fetch_identity(
            base_url=_member_base_url(member),
            model=member.model_name,
            api_key=crypto.unprotect(member.key_ciphertext),
            name=member.name,
            project_context=context,
            roster=roster,
        )
    except (
        crypto.CryptoError,
        ai_client.PlannerClientError,
        planner.PlanError,
    ) as exc:
        reason = getattr(exc, 'message', '') or '未知错误'
        _job_message(job,
            project_id=job.project_id,
            member_id=member.pk,
            role=ChatMessage.Role.ASSISTANT,
            content=f'我加入了，但自我介绍没生成成功：{reason}。可以先在左侧配置我。',
            payload={'source': 'error'},
        )
        return

    member.role = data['role'] or member.role
    member.duty = data['duty']
    member.persona = data['persona'] or member.persona
    job_queue.ensure_active(job.pk)
    member.save(update_fields=['role', 'duty', 'persona'])
    _job_message(job,
        project_id=job.project_id,
        member_id=member.pk,
        role=ChatMessage.Role.ASSISTANT,
        content=data['intro'] or f'我是 {member.name}，负责{member.role or "协作"}。',
        payload={'source': 'identity'},
    )


def _attach_discussion_draft(
    job: ReplyJob, drafter: Member, transcript: list[str]
) -> None:
    """After the discussion, turn the conclusion into a confirmable task draft."""
    project = job.project
    members = list(project.members.filter(is_active=True))
    start, end = planner.window(project)
    identity = user_profile.prompt_block(project)
    try:
        raw = ai_client.fetch_plan(
            base_url=_member_base_url(drafter),
            model=drafter.model_name,
            api_key=crypto.unprotect(drafter.key_ciphertext),
            objective=job.prompt,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            instructions=(
                '讨论记录：\n'
                + '\n\n'.join(transcript)
                + (
                    '\n\n按立项会结论拆任务。每个任务除 title/detail/parent_ref/assignee_id 外，'
                    '必须给出 why（为什么做，人话）、outcome（做完是什么样）、estimate（人话工期）、'
                    'acceptance（可判定的验收）、guide（summary/steps/outcomes）、'
                    'execution_spec（work_kind/risk/allowed_paths/check_commands）。'
                    '负责人要覆盖不同用户画像相关的工作，不要全给同一个成员。'
                    if job.prompt.startswith('【立项会】')
                    else '\n\n请按讨论结论拆成任务树，任务要细，负责人按成员角色分配。'
                )
                + (('\n\n用户身份与拆分视角：\n' + identity) if identity else '')
            ),
            members=[
                {
                    'id': item.pk,
                    'name': item.name,
                    'kind': item.kind,
                    'role': item.role,
                    'persona': item.persona,
                }
                for item in members
            ],
        )
        tasks = assignment.fill(planner.validate(raw, members, start, end), project)
    except (
        crypto.CryptoError,
        ai_client.PlannerClientError,
        planner.PlanError,
    ) as exc:
        reason = getattr(exc, 'message', '') or '未知错误'
        _job_message(job,
            project_id=job.project_id,
            role=ChatMessage.Role.SYSTEM,
            content=f'草案没生成成功（{drafter.name} / {drafter.model_name or "未填模型"}）：{reason}',
        )
        return

    _job_message(job,
        project_id=job.project_id,
        member_id=drafter.pk,
        role=ChatMessage.Role.ASSISTANT,
        content=f'根据讨论，我拆了一版 {len(tasks)} 个任务的草案，确认后写入任务树。',
        payload={'source': 'discussion-draft', 'tasks': tasks},
    )


def _run_agent_job(job: ReplyJob) -> None:
    """Let one AI inspect the project (read-only) and write a plan."""
    member = job.member
    project = job.project
    if member is None:
        raise crypto.CryptoError('成员已被删除。')

    def on_step(index: int, steps: list[dict]) -> None:
        lines = []
        for position, step in enumerate(steps, 1):
            argument = step['args'].get('path') or step['args'].get('query') or ''
            lines.append(f'{position}. {step["tool"]} {argument}'.strip())
        _save_progress(job.pk, '正在查看项目…\n' + '\n'.join(lines), '', 'agent')

    answer, steps = agent.run(
        base_url=_member_base_url(member),
        model=member.model_name,
        api_key=crypto.unprotect(member.key_ciphertext),
        user_message=job.prompt,
        project=project,
        tasks=list(project.tasks.all()[:12]),
        library=list(project.library.all()[:8]),
        on_step=on_step,
    )
    _job_message(job,
        project_id=job.project_id,
        member_id=member.pk,
        role=ChatMessage.Role.ASSISTANT,
        content=answer,
        payload={
            'source': 'agent',
            'steps': steps,
            'workspace': str(agent_tools.root()),
        },
    )


def _run_job(job_id: int) -> None:
    """Background worker: call the model, then write the message unless cancelled."""
    close_old_connections()
    try:
        job = (
            ReplyJob.objects.select_related('project', 'member')
            .filter(pk=job_id)
            .first()
        )
        if job is None or not job_queue.active(job_id):
            return
        if job.member is None and job.mode != ReplyJob.Mode.DISCUSS:
            job_queue.update_active(job_id, status=ReplyJob.Status.FAILED,
                                    error='AI成员已被删除，请选择可用成员后重新发送。',
                                    finished_at=timezone.now())
            return
        member_label = _member_label(job.member) if job.member else '讨论'
        try:
            if job.mode == ReplyJob.Mode.AGENT:
                _run_agent_job(job)
                if (not job_queue.active(job_id)):
                    return
                job_queue.update_active(job_id,
                    status=ReplyJob.Status.DONE, finished_at=timezone.now()
                )
                return
            if job.mode == ReplyJob.Mode.IDENTITY:
                _run_identity(job)
                if (not job_queue.active(job_id)):
                    return
                job_queue.update_active(job_id,
                    status=ReplyJob.Status.DONE, finished_at=timezone.now()
                )
                return
            if job.mode == ReplyJob.Mode.DISCUSS:
                _run_discussion(job)
                if (not job_queue.active(job_id)):
                    return
                job_queue.update_active(job_id,
                    status=ReplyJob.Status.DONE, finished_at=timezone.now()
                )
                return

            if job.mode in (ReplyJob.Mode.PLAN, ReplyJob.Mode.REVIEW):
                _save_progress(job.pk, '', '', 'planning')
                content, payload = _run_one(job)
            else:
                streamed = _stream_one(job)
                if streamed is None:
                    return
                content = streamed['text']
                payload = {
                    'source': 'chat',
                    'reasoning': streamed['reasoning'],
                    'reasoning_source': streamed['reasoning_source'],
                }
        except (
            crypto.CryptoError,
            ai_client.PlannerClientError,
            planner.PlanError,
        ) as exc:
            reason = getattr(exc, 'message', '') or '未知错误'
            content = f'调用 {member_label} 失败：{reason}'
            payload = {'source': 'error'}

        if (not job_queue.active(job_id)):
            return

        job_queue.ensure_active(job_id)
        from . import directives

        content, actions = directives.apply_with_log(job.project, content)
        if actions:
            payload = {**payload, 'actions': actions}
        _job_message(job,
            project_id=job.project_id,
            member_id=job.member_id,
            role=ChatMessage.Role.ASSISTANT,
            content=content,
            payload=payload,
        )
        job_queue.update_active(job_id,
            status=ReplyJob.Status.FAILED if payload.get('source') == 'error' else ReplyJob.Status.DONE,
            finished_at=timezone.now()
        )
    finally:
        close_old_connections()


def _parse_date(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


@require_http_methods(['GET', 'POST'])
def profile_view(request):
    profile = user_profile.current_profile(request)
    if profile is None:
        return redirect('projects:index')
    roles = dict(UserProfile.Role.choices)
    if request.method == 'POST':
        role = request.POST.get('role', '')
        if role in roles:
            profile.role = role
        profile.secondary_roles = [
            item for item in request.POST.getlist('secondary') if item in roles
        ]
        profile.domain = (request.POST.get('domain') or '').strip()[:80]
        profile.experience = (request.POST.get('experience') or '').strip()[:40]
        profile.stack = (request.POST.get('stack') or '').strip()[:200]
        profile.goal = (request.POST.get('goal') or '').strip()[:2000]
        profile.save()
        return redirect('projects:index')
    return render(
        request,
        'projects/profile.html',
        {'profile': profile, 'roles': UserProfile.Role.choices},
    )


def index(request):
    if (
        request.method == 'GET'
        and is_server()
        and request.user.is_authenticated
        and not UserProfile.objects.filter(user=request.user).exists()
    ):
        return redirect('projects:profile')
    from .collaboration import default_policy
    local_mode = not is_server()
    first_project = local_mode and not Project.objects.exists()
    error = ''
    name = (request.POST.get('name') or '').strip()
    goal = (request.POST.get('goal') or '').strip()
    onboarding_role = (request.POST.get('onboarding_role') or '').strip() if local_mode else ''
    if request.method == 'POST':
        if not name or not goal:
            error = '项目名称和目标都要填。'
        elif len(name) > 120 or len(goal) > 200:
            error = '项目名称最多120字，目标最多200字，请精简后再创建。'
        elif onboarding_role and onboarding_role not in dict(UserProfile.Role.choices):
            error = '请选择列表中的身份，或稍后再选。'
        else:
            with transaction.atomic():
                owner = request.user if request.user.is_authenticated else (
                    user_profile.local_user() if local_mode else None
                )
                project = Project.objects.create(
                    name=name[:120],
                    goal_title=goal[:200],
                    owner=owner,
                    policy=default_policy() if is_server() else {},
                )
                if onboarding_role:
                    profile, _ = UserProfile.objects.get_or_create(user=owner)
                    profile.role = onboarding_role
                    profile.save(update_fields=['role'])
                human_name = (
                    request.user.get_username() if request.user.is_authenticated else '我'
                )
                Member.objects.create(
                    project=project,
                    kind=Member.Kind.HUMAN,
                    name=human_name[:80],
                    role='负责人',
                    user=owner,
                )
                if request.user.is_authenticated:
                    ProjectMembership.objects.create(
                        project=project,
                        user=request.user,
                        role=ProjectMembership.Role.OWNER,
                    )
                Member.objects.create(
                    project=project,
                    kind=Member.Kind.AI,
                    name='DeepSeek',
                    role='后端',
                    provider='deepseek',
                    model_name='deepseek-v4-flash',
                )
            if first_project:
                return redirect(_space_url(project, tab='chat') + '&welcome=1')
            return redirect('projects:space', pk=project.pk)
    projects = (
        visible_projects(request.user if request.user.is_authenticated else None)
        .prefetch_related('members')
        .annotate(
            total_tasks=Count('tasks', distinct=True),
            done_tasks=Count(
                'tasks',
                filter=Q(tasks__status=Task.Status.DONE),
                distinct=True,
            ),
        )
        .order_by('-created_at')
    )
    if local_mode:
        from .progress import summarize
        task_rows = Task.objects.select_related('project', 'assignee').prefetch_related(
            Prefetch('prerequisites', queryset=Task.objects.select_related('assignee')),
            Prefetch('deliveries', queryset=Delivery.objects.only('id', 'task_id', 'status', 'review_note')),
        )
        projects = list(projects.prefetch_related(Prefetch('tasks', queryset=task_rows)))
        for project in projects:
            project.personal_progress = summarize(project.tasks.all())
    return render(
        request,
        'projects/index.html',
        {
            'projects': projects,
            'error': error,
            'first_project': first_project,
            'onboarding_roles': UserProfile.Role.choices,
            'entered_name': name,
            'entered_goal': goal,
            'entered_role': onboarding_role,
            'workroom_user': (
                request.user if request.user.is_authenticated else None
            ),
        },
    )


@require_POST
def project_delete(request, pk: int):
    project = project_for(request, pk, owner=True)
    audit(project, request.user, 'project.delete', project.name)
    project.delete()
    return redirect('projects:index')


def _connect_context(results=None):
    command, args = mcp_clients.mcp_command()
    config = {'mcpServers': {'workroom': {'command': command, 'args': args}}}
    nl = chr(10)
    toml = (
        '[mcp_servers.workroom]' + nl
        + f'command = {json.dumps(command, ensure_ascii=False)}' + nl
        + f'args = {json.dumps(args, ensure_ascii=False)}'
    )
    return {
        'config_json': json.dumps(config, ensure_ascii=False, indent=2),
        'config_toml': toml,
        'server_path': args[0] if args and args[0].endswith('.py') else command,
        'results': results or [],
    }


@require_GET
def _from_pk(request) -> str:
    """Project id passed by the rail so child pages can return to the workspace."""
    value = str(request.GET.get('from', '')).strip()
    # 只有数字能当 pk 用，否则 {% url %} 会抛 NoReverseMatch
    return value if value.isdigit() else ''


def connect(request):
    if is_server():
        from django.conf import settings as django_settings

        return render(
            request,
            'projects/connect.html',
            {
                'server_mode': True,
                'workroom_server_url': getattr(
                    django_settings, 'WORKROOM_SERVER_URL', ''
                ),
                'config_json': '',
                'config_toml': '',
                'server_path': '',
                'results': [],
                'clients': [],
                'from_pk': _from_pk(request),
            },
        )
    context = _connect_context()
    context['clients'] = mcp_clients.status()
    context['from_pk'] = _from_pk(request)
    return render(request, 'projects/connect.html', context)


@require_POST
def connect_client(request, client='all'):
    if is_server():
        raise Http404('server mode does not modify host client configs')
    specs = mcp_clients.client_specs()
    keys = list(specs) if client == 'all' else [client]
    results = []
    for key in keys:
        label = specs.get(key, {}).get('label', key)
        try:
            path = mcp_clients.connect(key)
        except mcp_clients.ClientError as exc:
            results.append({'label': label, 'ok': False, 'text': exc.message})
        else:
            results.append({'label': label, 'ok': True, 'text': f'已写入 {path}'})
    context = _connect_context(results)
    context['clients'] = mcp_clients.status()
    return render(request, 'projects/connect.html', context)


@require_GET
def space(request, pk: int):
    project = project_for(request, pk)
    tab = request.GET.get('tab') or 'tasks'
    if tab not in TABS or (is_server() and tab == 'progress'):
        tab = 'tasks'

    from django.db.models import Prefetch

    from .task_explanations import prepare
    tasks = list(project.tasks.select_related('assignee', 'parent', 'project').prefetch_related(
        Prefetch('prerequisites', queryset=Task.objects.select_related('assignee')),
        Prefetch('deliveries', queryset=Delivery.objects.only('id', 'task_id', 'status', 'review_note')),
    ))
    selected = None
    raw_task = request.GET.get('task', '')
    if raw_task.isdigit():
        selected = next((task for task in tasks if task.pk == int(raw_task)), None)
    raw_focus = request.GET.get('focus', '')
    show_archive = request.GET.get('archive') == '1'
    # 一次建好父子索引，后面全在内存里走，避免逐个 children.all() 打库
    by_parent: dict[int | None, list] = {}
    for task in tasks:
        by_parent.setdefault(task.parent_id, []).append(task)
    for bucket in by_parent.values():
        bucket.sort(key=lambda item: item.order)

    archive_ids: set[int] = set()
    stack = [
        task
        for task in tasks
        if task.parent_id is None and task.title.startswith('归档')
    ]
    while stack:
        node = stack.pop()
        if node.pk in archive_ids:
            continue
        archive_ids.add(node.pk)
        stack.extend(by_parent.get(node.pk, []))
    hidden: set[int] = archive_ids if not show_archive else set()
    visible_tasks = [task for task in tasks if task.pk not in hidden]

    # 任务筛选：关键字 / 状态 / 负责人。命中子任务时保留其上级，避免树断掉。
    task_query = (request.GET.get('q') or '').strip()
    task_status = (request.GET.get('status') or '').strip()
    assignee_filter = (request.GET.get('assignee') or '').strip()
    filtering_tasks = bool(task_query or task_status or assignee_filter)
    if filtering_tasks:
        needle = task_query.lower()
        matched = [
            task
            for task in visible_tasks
            if (
                not needle
                or needle in task.title.lower()
                or needle in (task.detail or '').lower()
            )
            and (not task_status or task.status == task_status)
            and (not assignee_filter or str(task.assignee_id or '') == assignee_filter)
        ]
        keep: set[int] = set()
        by_id = {task.pk: task for task in tasks}
        for task in matched:
            node = task
            while node is not None and node.pk not in keep:
                keep.add(node.pk)
                node = by_id.get(node.parent_id)
        visible_tasks = [task for task in visible_tasks if task.pk in keep]

    leaves = [task for task in visible_tasks if task.parent_id is not None]
    next_task = next(
        (task for task in leaves if task.status == Task.Status.DOING), None
    ) or next((task for task in leaves if task.status == Task.Status.TODO), None)
    progress = None
    if not is_server():
        from .progress import summarize
        progress = summarize(tasks)
        if not filtering_tasks:
            next_task = progress['next']['row']['task'] if progress['next'] else None
    lifecycle = next(
        (task for task in visible_tasks if task.parent_id is None and task.title.startswith('10 ')),
        None,
    )
    timeline = []
    if lifecycle is not None:
        for stage in by_parent.get(lifecycle.pk, []):
            items = []
            for child in by_parent.get(stage.pk, []):
                grand = by_parent.get(child.pk)
                if grand:
                    items.extend(grand)
                else:
                    items.append(child)
            rolled = _stage_status(stage, items)
            if rolled != stage.status:
                Task.objects.filter(pk=stage.pk).update(status=rolled)
                stage.status = rolled
            timeline.append({
                'stage': stage,
                'items': items,
                'status': rolled,
                'status_label': dict(Task.Status.choices).get(rolled, ''),
                'done_count': sum(1 for item in items if item.status == Task.Status.DONE),
                'total_count': len(items),
            })
    raw_chain = (request.GET.get('chain') or '').strip()
    chain_view = None
    if raw_chain.isdigit():
        focus_task = next((t for t in visible_tasks if t.pk == int(raw_chain)), None)
        if focus_task is not None:
            chain_view = chain.build(project, focus_task.pk)
            chain_view['focus_task'] = focus_task
            chain_view['names'] = {t.pk: t.title for t in visible_tasks}
    task_branches = prepare(visible_tasks, int(raw_focus) if raw_focus.isdigit() else None)
    requested_view = request.GET.get('view')
    task_view = requested_view if requested_view in {'outline', 'graph'} else (
        'timeline' if timeline else 'outline'
    )

    library = list(project.library.select_related('task').all())
    kind_filter = request.GET.get('kind') or ''
    if kind_filter not in dict(LibraryEntry.Kind.choices):
        kind_filter = ''
    query = (request.GET.get('q') or '').strip()
    library_visible = [
        item
        for item in library
        if (not kind_filter or item.kind == kind_filter)
        and (
            not query
            or query.lower()
            in f'{item.title} {item.summary} {item.body} {item.tags}'.lower()
        )
    ]
    selected_entry = None
    raw_entry = request.GET.get('entry', '')
    if raw_entry.isdigit():
        selected_entry = next(
            (item for item in library if item.pk == int(raw_entry)), None
        )
    groups = [
        {
            'value': value,
            'label': label,
            'entries': [item for item in library if item.kind == value],
        }
        for value, label in LibraryEntry.Kind.choices
    ]

    cut = timezone.now() - timedelta(minutes=10)
    if is_server():
        job_queue.recover_stale()
    elif tab != 'progress':
        project.jobs.filter(
            status=ReplyJob.Status.RUNNING, created_at__lt=cut
        ).update(status=ReplyJob.Status.FAILED, finished_at=timezone.now())
    pending_jobs = list(
        project.jobs.filter(
            status__in=[ReplyJob.Status.QUEUED, ReplyJob.Status.RUNNING]
        )
        .select_related('member')
        .order_by('created_at', 'id')
    )
    stale_workers = job_queue.worker_health()
    membership = (
        ProjectMembership.objects.filter(project=project, user=request.user).first()
        if request.user.is_authenticated
        else None
    )
    live_member = (
        project.members.filter(user=request.user, is_active=True).first()
        if request.user.is_authenticated
        else None
    )

    members = list(project.members.filter(is_active=True))
    joined_tools = {
        member.tool for member in members if member.kind == Member.Kind.EXTERNAL
    }
    external_options = (
        []
        if is_server()
        else [
            {'key': item['key'], 'label': item['label']}
            for item in mcp_clients.status()
            if item['configured'] and item['key'] not in joined_tools
        ]
    )
    # 聊天记录分页：一次只渲染最近 40 条，往上翻再取，避免几千节点拖慢首屏
    chat_page = 20
    raw_before = (request.GET.get('before') or '').strip()
    chat_query = project.messages.select_related('member').order_by('-id')
    if raw_before.isdigit():
        chat_query = chat_query.filter(id__lt=int(raw_before))
    messages = list(chat_query[:chat_page])
    messages.reverse()
    has_earlier = bool(messages) and project.messages.filter(
        id__lt=messages[0].pk
    ).exists()
    earliest_id = messages[0].pk if messages else ''
    for message in messages:
        message.draft_preview = planner.preview_draft(message.draft_tasks)
    ai_members = [member for member in members if member.kind == Member.Kind.AI]
    ready_ai = [member for member in ai_members if member.has_key]
    ai_choice = request.GET.get('ai') or request.COOKIES.get(
        f'ai_{project.pk}', ''
    )
    selected_ai = next(
        (member for member in ready_ai if str(member.pk) == ai_choice), None
    )
    if ai_choice == 'all' and len(ready_ai) > 1:
        ai_label = f'讨论 · {len(ready_ai)} 个 AI'
        ai_picker_label = ai_label
    else:
        ai_choice = str(selected_ai.pk) if selected_ai else ''
        if selected_ai is None and ready_ai:
            selected_ai = ready_ai[0]
            ai_choice = str(selected_ai.pk)
        ai_label = (
            f'{selected_ai.name} · {selected_ai.model_name}'
            if selected_ai is not None
            else '演示响应 · 未连接模型'
        )
        ai_picker_label = (
            f'{selected_ai.name} · {selected_ai.role}'
            if selected_ai is not None and selected_ai.role
            else (selected_ai.name if selected_ai is not None else '由谁回答')
        )
    total = len(tasks)
    done = sum(1 for task in tasks if task.is_done)
    selected_children = (
        [task for task in tasks if selected and task.parent_id == selected.pk]
        if selected
        else []
    )
    selected_delivery = None
    if selected:
        selected_delivery = selected.deliveries.order_by('-created_at').first()
    return render(
        request,
        'projects/space.html',
        {
            'project': project,
            'projects': visible_projects(request.user if request.user.is_authenticated else None),
            'tab': tab,
            'tree': build_tree(visible_tasks),
            'task_branches': task_branches,
            'task_view': task_view,
            'next_task': next_task,
            'progress': progress,
            'timeline': timeline,
            'chain_view': chain_view,
            'show_archive': show_archive,
            'archived_total': len(hidden),
            'visible_total': len(visible_tasks),
            'task_query': task_query,
            'task_status': task_status,
            'assignee_filter': assignee_filter,
            'assignee_options': [m for m in project.members.all() if m.is_active],
            'filtering_tasks': bool(task_query or task_status or assignee_filter),
            'selected_is_archived': bool(selected and selected.pk in archive_ids),
            'done_visible': sum(
                1 for task in visible_tasks if task.status == Task.Status.DONE
            ),
            'percent_visible': (
                round(
                    100
                    * sum(1 for task in visible_tasks if task.status == Task.Status.DONE)
                    / len(visible_tasks)
                )
                if visible_tasks
                else 0
            ),
            'selected': selected,
            'selected_children': selected_children,
            'selected_package': _execution_preview(selected) if selected else None,
            'selected_delivery': selected_delivery,
            'drift_hint': drift.hint(project, Path(settings.BASE_DIR)),
            'members': members,
            'mention_candidates': _mention_candidates(members),
            'submission_id': str(uuid.uuid4()),
            'product_definition': _product_definition(library),
            'membership': membership,
            'membership_role': membership.role if membership else '',
            'can_manage': (
                not is_server()
                or (membership is not None and membership.role == ProjectMembership.Role.OWNER)
            ),
            'can_edit': (
                not is_server()
                or (
                    membership is not None
                    and membership.role
                    in (ProjectMembership.Role.OWNER, ProjectMembership.Role.EDITOR)
                )
            ),
            'external_options': external_options,
            'messages': messages,
            'has_earlier': has_earlier,
            'earliest_id': earliest_id,
            'library': library,
            'library_visible': library_visible,
            'kind_filter': kind_filter,
            'query': query,
            'tasks': tasks,
            'library_groups': groups,
            'library_count': len(library),
            'selected_entry': selected_entry,
            'kind_choices': LibraryEntry.Kind.choices,
            'pending_jobs': pending_jobs,
            'failed_jobs': list(project.jobs.filter(status=ReplyJob.Status.FAILED)
                                .select_related('member').order_by('-id')[:5]),
            'worker_health': stale_workers,
            'server_mode': is_server(),
            'show_welcome': not is_server() and request.GET.get('welcome') == '1',
            'workroom_user': (
                request.user if request.user.is_authenticated else None
            ),
            'live_member': live_member,
            'ai_label': ai_label,
            'agent_root': '' if is_server() else str(agent_tools.root()),
            'agent_available': (not is_server()) and agent_tools.root().is_dir(),
            'ai_members': ready_ai,
            'selected_ai': selected_ai,
            'ai_choice': ai_choice,
            'ai_picker_label': ai_picker_label,
            'node_w': NODE_WIDTH,
            'node_h': NODE_HEIGHT,
            'total': total,
            'done': done,
            'percent': round(done * 100 / total) if total else 0,
            'status_choices': Task.Status.choices,
        },
    )


@require_http_methods(['GET', 'POST'])
def member_create(request, pk: int):
    project = project_for(request, pk, write=True, owner=True)
    if request.method == 'POST':
        form = NewMemberForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                sealed = crypto.protect(data['api_key'])
            except crypto.CryptoError as exc:
                form.add_error(None, exc.message)
            else:
                preset = personas.next_for_project(project)
                member = Member.objects.create(
                    project=project,
                    kind=Member.Kind.AI,
                    name=data['name'][:80],
                    role=preset['role'],
                    duty=preset['duty'],
                    persona=preset['persona'],
                    provider=data['provider'],
                    model_name=data['resolved_model'],
                    base_url=(
                        data['resolved_base_url']
                        if data['provider'] == providers.CUSTOM
                        else ''
                    ),
                    key_ciphertext=sealed,
                )
                _start_job(project, member, '', ReplyJob.Mode.IDENTITY)
                return redirect(_space_url(project, tab='chat'))
    else:
        form = NewMemberForm(initial={'provider': providers.DEFAULT})
    return render(
        request,
        'projects/member_new.html',
        {'project': project, 'form': form},
    )


@require_POST
def member_join_external(request, pk: int, client: str):
    if is_server():
        raise Http404('server mode does not inspect host client configs')
    project = project_for(request, pk, write=True, owner=True)
    specs = mcp_clients.client_specs()
    spec = specs.get(client)
    if spec is None:
        raise Http404('unknown client')
    configured = {item['key']: item['configured'] for item in mcp_clients.status()}
    if not configured.get(client):
        return redirect(_space_url(project, tab='chat'))

    member = project.members.filter(tool=client).first()
    if member is None:
        Member.objects.create(
            project=project,
            kind=Member.Kind.EXTERNAL,
            tool=client,
            name=spec['label'],
            role='执行',
        )
    elif not member.is_active:
        member.is_active = True
        member.kind = Member.Kind.EXTERNAL
        member.save(update_fields=['is_active', 'kind'])
    return redirect(_space_url(project, tab='chat'))


@require_POST
def member_stop(request, pk: int, member_id: int):
    project = get_object_or_404(Project, pk=pk)
    member = get_object_or_404(
        Member, pk=member_id, project=project, is_active=True
    )
    if member.kind != Member.Kind.EXTERNAL:
        raise Http404('not an external member')
    ChatMessage.objects.create(
        project=project,
        role=ChatMessage.Role.SYSTEM,
        content=f'已请求 {member.name} 停止当前工作；它下次轮询时生效。',
        payload={
            'control': 'stop',
            'member': member.pk,
            'consumed': False,
        },
    )
    return redirect(_space_url(project, tab='chat'))


@require_POST
def member_delete(request, pk: int, member_id: int):
    project = project_for(request, pk, write=True, owner=True)
    member = get_object_or_404(Member, pk=member_id, project=project)
    if member.kind not in (Member.Kind.AI, Member.Kind.EXTERNAL):
        raise Http404('member not found')

    name = member.name
    member.is_active = False
    member.key_ciphertext = ''
    member.save(update_fields=['is_active', 'key_ciphertext'])
    ChatMessage.objects.create(
        project=project,
        role=ChatMessage.Role.SYSTEM,
        content=f'已把 {name} 移出团队，历史消息和任务记录保留。',
    )
    next_url = (request.POST.get('next') or '').strip()
    if not next_url.startswith(f'/p/{project.pk}/'):
        next_url = _space_url(project, tab='chat')
    return redirect(next_url)


@require_http_methods(['GET', 'POST'])
def member_settings(request, pk: int, member_id: int):
    project = project_for(request, pk, write=True, owner=True)
    member = get_object_or_404(Member, pk=member_id, project=project)
    if not member.is_active or member.kind == Member.Kind.HUMAN:
        raise Http404('member not found')

    if member.kind == Member.Kind.EXTERNAL:
        if request.method == 'POST':
            external_form = ExternalMemberForm(request.POST)
            if external_form.is_valid():
                member.name = external_form.cleaned_data['name']
                member.role = (external_form.cleaned_data.get('role') or '').strip()
                member.persona = (
                    external_form.cleaned_data.get('persona') or ''
                ).strip()
                member.save(update_fields=['name', 'role', 'persona'])
                return redirect(_space_url(project, tab='chat'))
        else:
            external_form = ExternalMemberForm(
                initial={
                    'name': member.name,
                    'role': member.role,
                    'persona': member.persona,
                }
            )
        return render(
            request,
            'projects/external_member.html',
            {'project': project, 'member': member, 'form': external_form},
        )

    if request.method == 'POST' and request.POST.get('action') == 'optimize':
        _start_job(project, member, '', ReplyJob.Mode.IDENTITY)
        return redirect(_space_url(project, tab='chat'))

    if request.method == 'POST':
        form = MemberConfigForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if data.get('clear_key'):
                    member.key_ciphertext = ''
                elif data['api_key']:
                    member.key_ciphertext = crypto.protect(data['api_key'])
            except crypto.CryptoError as exc:
                form.add_error(None, exc.message)
            else:
                member.name = data['name']
                member.role = (data.get('role') or '').strip()
                member.duty = data.get('duty') or Member.Duty.EXECUTE
                member.persona = (data.get('persona') or '').strip()
                member.provider = data['provider']
                member.model_name = data['resolved_model']
                member.base_url = (
                    data['resolved_base_url']
                    if data['provider'] == providers.CUSTOM
                    else ''
                )
                member.save()
                return redirect(_space_url(project, tab='chat'))
    else:
        form = MemberConfigForm(
            initial={
                'name': member.name,
                'role': member.role,
                'duty': member.duty,
                'persona': member.persona,
                'provider': member.provider or providers.DEFAULT,
                'model_name': member.model_name,
                'base_url': member.base_url,
            }
        )

    return render(
        request,
        'projects/member_settings.html',
        {'project': project, 'member': member, 'form': form},
    )


@require_POST
def library_capture(request, pk: int, message_id: int):
    project = project_for(request, pk, write=True)
    message = get_object_or_404(
        ChatMessage,
        pk=message_id,
        project=project,
        role=ChatMessage.Role.ASSISTANT,
    )
    kind = request.POST.get('kind') or LibraryEntry.Kind.DECISION
    if kind not in dict(LibraryEntry.Kind.choices):
        kind = LibraryEntry.Kind.DECISION
    title = (request.POST.get('title') or '').strip()
    if not title:
        first = message.content.strip().splitlines()
        title = (first[0] if first else '对话结论')[:80]
    entry = LibraryEntry.objects.create(
        project=project,
        kind=kind,
        title=title[:160],
        summary=title[:200],
        body=message.content[:4000],
        source=LibraryEntry.Source.AI,
        source_ref=f'chat:{message.pk}',
    )
    library.bump_context(project)
    audit(project, request.user, 'library.capture', f'entry={entry.pk} title={entry.title}')
    return redirect(_space_url(project, tab='library', entry=entry))


@require_http_methods(['GET', 'POST'])
def library_edit(request, pk: int, entry_id: int):
    project = project_for(request, pk, write=True)
    entry = get_object_or_404(LibraryEntry, pk=entry_id, project=project)
    if request.method == 'POST':
        kind = request.POST.get('kind') or entry.kind
        if kind in dict(LibraryEntry.Kind.choices):
            entry.kind = kind
        entry.title = (request.POST.get('title') or entry.title).strip()[:160]
        entry.summary = (request.POST.get('summary') or '').strip()[:200]
        entry.body = (request.POST.get('body') or '').strip()
        entry.context = (request.POST.get('context') or '').strip()
        entry.options = (request.POST.get('options') or '').strip()
        entry.conclusion = (request.POST.get('conclusion') or '').strip()
        entry.tags = (request.POST.get('tags') or '').strip()[:120]
        raw_task = (request.POST.get('task') or '').strip()
        entry.task = (
            project.tasks.filter(pk=raw_task).first() if raw_task.isdigit() else None
        )
        entry.version += 1
        entry.save()
        library.bump_context(project)
        audit(
            project,
            request.user,
            'library.update',
            f'entry={entry.pk} version={entry.version}',
        )
        return redirect(_space_url(project, tab='library', entry=entry))

    return render(
        request,
        'projects/library_edit.html',
        {
            'project': project,
            'entry': entry,
            'tasks': project.tasks.all(),
            'kind_choices': LibraryEntry.Kind.choices,
        },
    )


@require_POST
def library_delete(request, pk: int, entry_id: int):
    project = project_for(request, pk, write=True)
    entry = get_object_or_404(LibraryEntry, pk=entry_id, project=project)
    audit(
        project,
        request.user,
        'library.delete',
        f'entry={entry.pk} title={entry.title} version={entry.version}',
    )
    entry.delete()
    library.bump_context(project)
    return redirect(_space_url(project, tab='library'))


@require_POST
def library_add(request, pk: int):
    project = project_for(request, pk, write=True)
    title = (request.POST.get('title') or '').strip()
    kind = request.POST.get('kind') or LibraryEntry.Kind.ARTIFACT
    body = (request.POST.get('body') or '').strip()
    raw_task = (request.POST.get('task') or '').strip()
    task = project.tasks.filter(pk=raw_task).first() if raw_task.isdigit() else None
    if title and kind in dict(LibraryEntry.Kind.choices):
        entry = LibraryEntry.objects.create(
            project=project,
            kind=kind,
            title=title[:160],
            body=body,
            task=task,
        )
        library.bump_context(project)
        audit(project, request.user, 'library.add', f'entry={entry.pk} title={entry.title}')
        return redirect(_space_url(project, tab='library', entry=entry))
    return redirect(_space_url(project, tab='library'))


_TASK_VERBS = re.compile(
    r'(改|做|加|删|实现|修|优化|检查|部署|写|设计|测试|接入|迁移|重构|发布|整理|验证)'
)


def _task_from_mention(project: Project, text: str, members: list[Member]):
    """Turn an @agent work request into a task; skip duplicates."""
    from . import directives

    if not members:
        return None
    cleaned = re.sub(r'@\S+', '', text).strip()
    if len(cleaned) < 8 or not _TASK_VERBS.search(cleaned):
        return None
    title = cleaned.splitlines()[0][:60]
    member = members[0]
    exists = project.tasks.filter(
        assignee=member, title=title,
        status__in=[Task.Status.TODO, Task.Status.DOING],
    ).exists()
    if exists:
        return None
    stage = directives.pick_stage(project, title)
    return Task.objects.create(
        project=project,
        parent=stage,
        title=title,
        detail=text,
        assignee=member,
        status=Task.Status.TODO,
        guide={'summary': cleaned[:180]},
    )


@require_POST
def chat_send(request, pk: int):
    project = project_for(request, pk, write=True)
    text = (request.POST.get('message') or '').strip()
    if not text:
        return redirect(_space_url(project, tab='chat'))

    def error(reason, status=400):
        return render(request, 'projects/chat_error.html',
                      {'project': project, 'error': reason, 'message': text}, status=status)

    if len(text) > 2000:
        return error('消息最多2000字，请缩短后重新发送。')
    raw_id = (request.POST.get('submission_id') or '').strip()
    submission = {}
    if raw_id:
        try:
            if len(raw_id) > 64:
                raise ValueError('invalid form id')
            request_id = str(uuid.UUID(raw_id))
        except ValueError:
            return error('发送编号无效，请返回对话，重新打开表单后发送。')
        submission = {'submission_id': request_id, 'sender_id': request.user.pk or 0,
                      'submission_mode': request.POST.get('mode') or '',
                      'submission_ai': request.POST.get('ai') or ''}

    # Keep the replay decision and all DB changes together; network work starts
    # via on_commit, so a rolled-back message never triggers a provider call.
    with transaction.atomic():
        if submission:
            Project.objects.select_for_update().only('pk').get(pk=project.pk)
            previous = project.messages.filter(role=ChatMessage.Role.USER,
                payload__submission_id=submission['submission_id'],
                payload__sender_id=submission['sender_id']).first()
            if previous:
                if previous.content != text or any(previous.payload.get(k) != v for k, v in submission.items()):
                    return error('这个发送编号已经用于另一条消息。请返回对话，使用新表单发送。', 409)
                return redirect(_space_url(project, tab='chat'))
        return _chat_send_once(request, project, text, submission)


def _chat_send_once(request, project, text, submission):

    mentions = _extract_mentions(project, text)
    created_task = _task_from_mention(project, text, mentions)
    ChatMessage.objects.create(
        project=project,
        role=ChatMessage.Role.USER,
        content=text,
        member=(project.members.filter(user=request.user, is_active=True).first()
                if request.user.is_authenticated else None),
        payload=dict(submission, **({'mentions': [member.pk for member in mentions]} if mentions else {})),
    )
    if (not is_server() or role_of(request.user, project) == 'owner') and _handle_team_command(project, text):
        return redirect(_space_url(project, tab='chat'))

    members = list(project.members.filter(is_active=True))
    ready_ai = [
        member
        for member in members
        if member.kind == Member.Kind.AI and member.has_key
    ]

    requested = request.POST.get('ai', '')
    mode = request.POST.get('mode') or ''
    ai_mentions = [
        member
        for member in mentions
        if member.kind == Member.Kind.AI and member.has_key
    ]
    external_mentions = [
        member for member in mentions if member.kind == Member.Kind.EXTERNAL
    ]
    if ai_mentions and not requested:
        requested = str(ai_mentions[0].pk)

    # @ 只叫了外部工具：不进 AI 队列，放进对方收件箱等它轮询。
    if external_mentions and not ai_mentions and mode != 'agent':
        names = '、'.join(member.name for member in external_mentions)
        ChatMessage.objects.create(
            project=project,
            role=ChatMessage.Role.SYSTEM,
            content=(
                f'已放进 {names} 的收件箱；它下次轮询时会看到这条消息，'
                '不需要 AI 代答。'
                + (f' 已建任务 #{created_task.pk}「{created_task.title}」，完成后回填状态。'
                   if created_task else '')
            ),
            payload={
                'source': 'mention-notify',
                'members': [member.pk for member in external_mentions],
            },
        )
        return redirect(_space_url(project, tab='chat'))

    if not ready_ai:
        if is_server():
            ChatMessage.objects.create(
                project=project,
                role=ChatMessage.Role.SYSTEM,
                content='这个项目还没有可用 AI：请项目所有者先在项目里配置模型 Key。',
            )
            return redirect(_space_url(project, tab='chat'))
        draft = demo.build_draft(project, text)
        ChatMessage.objects.create(
            project=project,
            role=ChatMessage.Role.ASSISTANT,
            content=draft['content'],
            payload={'tasks': draft['tasks'], 'source': 'demo'},
        )
        return redirect(_space_url(project, tab='chat'))

    if mode == 'agent' and ready_ai:
        if is_server():
            ChatMessage.objects.create(
                project=project,
                role=ChatMessage.Role.SYSTEM,
                content='服务器模式不读取云主机目录；只读 Agent 只在成员自己的电脑上可用。',
            )
            return redirect(_space_url(project, tab='chat'))
        member = next(
            (item for item in ready_ai if str(item.pk) == requested), None
        ) or ready_ai[0]
        _start_job(project, member, text, ReplyJob.Mode.AGENT, user=request.user)
        response = redirect(f'{_space_url(project, tab="chat")}&ai={member.pk}')
        response.set_cookie(
            f'ai_{project.pk}', str(member.pk), max_age=90 * 24 * 3600, samesite='Lax'
        )
        return response

    if mode == 'kickoff':
        _start_job(project, None, '【立项会】' + text, ReplyJob.Mode.DISCUSS)
        response = redirect(_space_url(project, tab='chat'))
        response.set_cookie(
            f'ai_{project.pk}', 'all', max_age=90 * 24 * 3600, samesite='Lax'
        )
        return response

    if requested == 'all' and len(ready_ai) > 1:
        _start_job(project, None, text, ReplyJob.Mode.DISCUSS, user=request.user)
        response = redirect(f'{_space_url(project, tab="chat")}&ai=all')
        response.set_cookie(
            f'ai_{project.pk}', 'all', max_age=90 * 24 * 3600, samesite='Lax'
        )
        return response

    member = next(
        (item for item in ready_ai if str(item.pk) == requested), None
    )
    if member is None:
        member = ready_ai[0]
    if mode == 'prompt':
        _start_job(project, member, '【提示词】' + text, ReplyJob.Mode.CHAT)
        response = redirect(_space_url(project, tab='chat'))
        response.set_cookie(
            f'ai_{project.pk}', str(member.pk), max_age=90 * 24 * 3600, samesite='Lax'
        )
        return response

    plan_mode = mode == 'plan'
    _start_job(
        project,
        member,
        text,
        ReplyJob.Mode.PLAN if plan_mode else ReplyJob.Mode.CHAT,
        user=request.user,
    )
    response = redirect(f'{_space_url(project, tab="chat")}&ai={member.pk}')
    response.set_cookie(
        f'ai_{project.pk}', str(member.pk), max_age=90 * 24 * 3600, samesite='Lax'
    )
    return response


@require_GET
def job_status(request, pk: int):
    project = project_for(request, pk)
    jobs = list(
        project.jobs.filter(
            status__in=[ReplyJob.Status.QUEUED, ReplyJob.Status.RUNNING]
        ).select_related('member')
    )
    now = timezone.now()
    running = [job for job in jobs if job.status == ReplyJob.Status.RUNNING]
    return JsonResponse(
        {
            'running': len(running),
            'queued': len([job for job in jobs if job.status == ReplyJob.Status.QUEUED]),
            'worker_online': job_queue.worker_online(),
            'jobs': [
                {
                    'id': job.pk,
                    'status': job.status,
                    'member': job.member.name if job.member else '',
                    'phase': job.phase,
                    'answer': job.partial_answer,
                    'reasoning': job.partial_reasoning,
                    'elapsed': max(0, int((now - job.created_at).total_seconds())),
                }
                for job in jobs
            ],
        }
    )


@require_POST
def job_cancel(request, pk: int, job_id: int):
    project = project_for(request, pk, write=True)
    job_queue.cancel(project, job_id, request.user)
    return redirect(_space_url(project, tab='chat'))


@require_POST
def draft_apply(request, pk: int, message_id: int):
    project = project_for(request, pk, write=True)
    first_root = None
    with transaction.atomic():
        message = get_object_or_404(
            ChatMessage.objects.select_for_update(),
            pk=message_id,
            project=project,
            role=ChatMessage.Role.ASSISTANT,
        )
        if message.applied_at is not None or not message.draft_tasks:
            return redirect(_space_url(project, tab='tasks'))

        try:
            dependencies = planner.dependency_refs(message.draft_tasks)
        except planner.PlanError as exc:
            return render(request, 'projects/draft_error.html', {'project': project, 'error': exc.message}, status=400)

        member_ids = set(
            project.members.filter(is_active=True).values_list('pk', flat=True)
        )
        base_order = project.tasks.aggregate(top=Max('order'))['top']
        base_order = 0 if base_order is None else base_order + 1
        created: dict[str, Task] = {}
        for offset, item in enumerate(message.draft_tasks):
            if not isinstance(item, dict):
                continue
            ref = str(item.get('ref') or '').strip()
            parent_ref = str(item.get('parent_ref') or '').strip() or None
            if parent_ref and parent_ref not in created:
                continue
            assignee_id = item.get('assignee_id')
            assignee = None
            if isinstance(assignee_id, int) and assignee_id in member_ids:
                assignee = project.members.filter(
                    is_active=True, pk=assignee_id
                ).first()
            guide = dict(item.get('guide')) if isinstance(item.get('guide'), dict) else {}
            for extra in ('why', 'outcome', 'estimate'):
                value = str(item.get(extra) or '').strip()
                if value:
                    guide.setdefault(extra, value)
            spec = item.get('execution_spec') if isinstance(item.get('execution_spec'), dict) else {}
            acceptance = str(item.get('acceptance') or '')
            if not guide and acceptance:
                guide = {'outcomes': collaboration.lines(acceptance)}
            task = Task.objects.create(
                project=project,
                parent=created.get(parent_ref) if parent_ref else None,
                title=str(item.get('title') or '未命名任务')[:160],
                detail=str(item.get('detail') or ''),
                acceptance=acceptance,
                guide=guide,
                execution_spec=spec,
                assignee=assignee,
                start_date=_parse_date(item.get('start_date')),
                end_date=_parse_date(item.get('end_date')),
                order=base_order + offset,
            )
            if ref:
                created[ref] = task
            if parent_ref is None and first_root is None:
                first_root = task

        for ref, required in dependencies.items():
            if required:
                created[ref].prerequisites.set(created[other] for other in required)

        message.applied_at = timezone.now()
        message.save(update_fields=['applied_at'])
    return redirect(_space_url(project, tab='tasks', task=first_root))


@require_POST
def prompt_apply(request, pk: int, message_id: int):
    project = project_for(request, pk, write=True)
    message = get_object_or_404(
        ChatMessage, pk=message_id, project=project, role=ChatMessage.Role.ASSISTANT
    )
    payload = message.payload if isinstance(message.payload, dict) else {}
    draft = payload.get('prompt_draft')
    if not isinstance(draft, dict):
        return redirect(_space_url(project, tab='chat'))
    data = {
        key: (request.POST.get(key) or draft.get(key) or '').strip()[:2000]
        for key in _PROMPT_FIELDS
    }
    prompt = chr(10).join(
        [
            f'你是{data["role"] or "项目协作者"}。',
            f'任务：{data["task"]}',
            f'上下文：{data["context"]}',
            f'目标：{data["goal"]}',
            f'约束：{data["constraints"]}',
            f'输出：{data["output"]}',
            f'验收：{data["acceptance"]}',
        ]
    )
    member = message.member or (
        project.members.filter(kind=Member.Kind.AI, is_active=True)
        .exclude(key_ciphertext='')
        .first()
    )
    if member is None:
        return redirect(_space_url(project, tab='chat'))
    _start_job(project, member, prompt, ReplyJob.Mode.CHAT)
    payload['prompt_applied'] = True
    payload['prompt_final'] = prompt
    message.payload = payload
    message.save(update_fields=['payload'])
    return redirect(_space_url(project, tab='chat'))


@require_POST
def prompt_regenerate(request, pk: int, message_id: int):
    """Ask for another draft of the same original wording."""
    project = project_for(request, pk, write=True)
    message = get_object_or_404(
        ChatMessage, pk=message_id, project=project, role=ChatMessage.Role.ASSISTANT
    )
    payload = message.payload if isinstance(message.payload, dict) else {}
    if not isinstance(payload.get('prompt_draft'), dict):
        return redirect(_space_url(project, tab='chat'))
    original = (payload.get('prompt_original') or '').strip()
    if not original:
        original = _prompt_original_from_history(project, message)
    if not original:
        return redirect(_space_url(project, tab='chat'))
    member = message.member or (
        project.members.filter(kind=Member.Kind.AI, is_active=True)
        .exclude(key_ciphertext='')
        .first()
    )
    if member is None:
        return redirect(_space_url(project, tab='chat'))
    _start_job(project, member, '【提示词】' + original, ReplyJob.Mode.CHAT)
    return redirect(_space_url(project, tab='chat'))


@require_http_methods(['GET', 'POST'])
def memory_view(request, pk: int):
    project = project_for(request, pk, write=request.method == 'POST')
    error = ''
    if request.method == 'POST':
        raw = (request.POST.get('workspace_path') or '').strip()
        path = Path(raw).expanduser() if raw else None
        if path is None or not path.is_dir():
            error = '路径不存在，或不是一个文件夹。'
        else:
            project.workspace_path = str(path)
            project.workspace_authorized_at = timezone.now()
            project.save(update_fields=['workspace_path', 'workspace_authorized_at'])
            room = path / '.workroom'
            (room / 'memory').mkdir(parents=True, exist_ok=True)
            memo = room / 'MEMORY.md'
            if not memo.exists():
                memo.write_text(
                    '# 长期记忆' + chr(10) + chr(10)
                    + '- 项目目标：' + project.goal_title + chr(10)
                    + '- 约定：' + chr(10),
                    encoding='utf-8',
                )
            daily = room / 'memory' / f'{timezone.localdate():%Y-%m-%d}.md'
            if not daily.exists():
                daily.write_text(
                    f'# {timezone.localdate():%Y-%m-%d}' + chr(10) + chr(10)
                    + '- 今天做了什么：' + chr(10)
                    + '- 决定：' + chr(10)
                    + '- 明天：' + chr(10),
                    encoding='utf-8',
                )
            audit(project, request.user, 'project.workspace', str(path))
            ChatMessage.objects.create(
                project=project,
                role=ChatMessage.Role.SYSTEM,
                content=f'工作区已授权：{path}；已创建 .workroom/MEMORY.md 与今日记录。',
                payload={'source': 'activity'},
            )
            return redirect('projects:memory', project.pk)
    files = []
    if project.workspace_path:
        room = Path(project.workspace_path) / '.workroom'
        for label, rel in [
            ('长期记忆', 'MEMORY.md'),
            ('今日记录', f'memory/{timezone.localdate():%Y-%m-%d}.md'),
        ]:
            target = room / rel
            if target.exists():
                files.append({'label': label, 'path': str(target), 'body': target.read_text(encoding='utf-8', errors='replace')[:6000]})
    activities = list(
        ChatMessage.objects.filter(project=project, role=ChatMessage.Role.SYSTEM)
        .order_by('-id')[:30]
    )
    return render(
        request,
        'projects/memory.html',
        {'project': project, 'files': files, 'activities': activities, 'error': error},
    )


@require_POST
def memory_pick(request, pk: int):
    if is_server():
        raise Http404()
    project_for(request, pk)
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askdirectory(title='选择工作区文件夹（可新建）')
        root.destroy()
    except Exception as exc:  # tkinter 不可用或没有桌面会话
        return JsonResponse({'path': '', 'error': str(exc)[:200]})
    return JsonResponse({'path': path or ''})


@require_POST
def task_create(request, pk: int):
    from django.db.models import Max
    from django.http import HttpResponseBadRequest

    from .permissions import role_of

    project = project_for(request, pk, write=True)
    title = (request.POST.get('title') or '').strip()[:160]
    if not title:
        return HttpResponseBadRequest('任务标题不能为空。')
    parent = None
    raw_parent = (request.POST.get('parent') or '').strip()
    if raw_parent:
        parent = project.tasks.filter(pk=raw_parent).first()
    assignee = None
    raw_assignee = (request.POST.get('assignee') or '').strip()
    if raw_assignee and role_of(request.user, project) == 'owner':
        assignee = project.members.filter(pk=raw_assignee, is_active=True).first()
    order = (project.tasks.aggregate(top=Max('order'))['top'] or 0) + 1
    task = Task.objects.create(
        project=project,
        parent=parent,
        title=title,
        detail=(request.POST.get('detail') or '').strip()[:8000],
        assignee=assignee,
        start_date=_parse_date(request.POST.get('start_date')),
        end_date=_parse_date(request.POST.get('end_date')),
        order=order,
    )
    audit(project, request.user, 'task.create', f'task={task.pk}')
    return redirect(_space_url(project, tab='tasks', task=task))


@require_POST
def task_assign(request, pk: int, task_id: int):
    project = project_for(request, pk, write=True, owner=True)
    task = get_object_or_404(Task, pk=task_id, project=project)
    raw = (request.POST.get('assignee') or '').strip()
    member = None
    if raw:
        member = project.members.filter(pk=raw, is_active=True).first()
    task.assignee = member
    task.save(update_fields=['assignee'])
    return redirect(_space_url(project, tab='tasks', task=task))


@require_POST
def task_acceptance(request, pk: int, task_id: int):
    project = project_for(request, pk, write=True, owner=True)
    task = get_object_or_404(Task, pk=task_id, project=project)
    task.acceptance = (request.POST.get('acceptance') or '').strip()[:4000]
    guide = task.guide if isinstance(task.guide, dict) else {}
    task.guide = dict(guide, outcomes=collaboration.lines(task.acceptance))
    task.save(update_fields=['acceptance', 'guide'])
    library.bump_context(project)
    return redirect(_space_url(project, tab='tasks', task=task))


@require_POST
def task_status(request, pk: int, task_id: int):
    project = project_for(request, pk, write=True)
    task = get_object_or_404(Task, pk=task_id, project=project)
    status = request.POST.get('status', '')
    if is_server() and status == Task.Status.DONE:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('请通过交付验收完成任务。')
    if status == Task.Status.DONE and task.deliveries.exists():
        return redirect('projects:task_delivery', pk=pk, task_id=task_id)
    if status in dict(Task.Status.choices):
        reason = (request.POST.get('blocked_reason') or '').strip()
        action = (request.POST.get('unblock_action') or '').strip()
        if status == Task.Status.BLOCKED and (not reason or not action):
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest('设为受阻前，请填写卡在哪里，以及需要谁做什么才能继续。')
        task.status = status
        task.blocked_reason = reason[:8000] if status == Task.Status.BLOCKED else ''
        task.unblock_action = action[:8000] if status == Task.Status.BLOCKED else ''
        task.save(update_fields=['status', 'blocked_reason', 'unblock_action'])
        audit(project, request.user, 'task.status', f'task={task.pk} status={status} reason={task.blocked_reason[:500]}')
        ChatMessage.objects.create(
            project=project,
            role=ChatMessage.Role.SYSTEM,
            content=(
                f'{(request.user.get_username() if request.user.is_authenticated else "我")}'
                f' 把「{task.title}」改为 {task.get_status_display()}'
            ),
            payload={'source': 'activity'},
        )
    return redirect(_space_url(project, tab='tasks', task=task))


@require_http_methods(['GET', 'POST'])
def knowledge(request, pk: int):
    """资料库知识库问答：检索资料库内容，回答必须带引用。"""
    project = project_for(request, pk)
    question = ''
    result = None
    error = ''
    notice = ''
    if request.method == 'POST':
        action = (request.POST.get('action') or 'ask').strip()
        if action == 'reindex':
            project = project_for(request, pk, write=True)
            try:
                stats = rag.index_project(
                    project, force=request.POST.get('force') == '1'
                )
                notice = (
                    f'已重建索引：新增 {stats["created"]} 块，'
                    f'跳过 {stats["skipped"]} 条未变化资料。'
                )
            except rag.RagError as exc:
                error = str(exc)
        else:
            question = (request.POST.get('q') or '').strip()
            if not question:
                error = '先输入一个问题。'
            else:
                try:
                    result = rag.answer(project, question)
                except rag.RagError as exc:
                    error = str(exc)
    status = rag.index_status(project)
    return render(
        request,
        'projects/knowledge.html',
        {
            'project': project,
            'status': status,
            'question': question,
            'result': result,
            'error': error,
            'notice': notice,
        },
    )


ARCHIVE_TITLE = '归档'


def _archive_root(project: Project, create: bool = False):
    root = (
        project.tasks.filter(parent__isnull=True, title__startswith=ARCHIVE_TITLE)
        .order_by('pk')
        .first()
    )
    if root is None and create:
        root = Task.objects.create(
            project=project, title=ARCHIVE_TITLE, status=Task.Status.DONE
        )
    return root


def _log_task_action(request, project: Project, task: Task, text: str, action: str) -> None:
    actor = request.user.get_username() if request.user.is_authenticated else '我'
    audit(project, request.user, action, f'task={task.pk}')
    ChatMessage.objects.create(
        project=project,
        role=ChatMessage.Role.SYSTEM,
        content=f'{actor} {text}「{task.title}」',
        payload={'source': 'activity'},
    )


@require_POST
def task_archive(request, pk: int, task_id: int):
    """把任务移到「归档」分支：默认视图里隐藏，归档视图里可恢复。"""
    project = project_for(request, pk, write=True)
    task = get_object_or_404(Task, pk=task_id, project=project)
    root = _archive_root(project, create=True)
    if task.pk == root.pk or task.parent_id == root.pk:
        return redirect(_space_url(project, tab='tasks'))
    task.parent = root
    task.save(update_fields=['parent'])
    _log_task_action(request, project, task, '归档了', 'task.archive')
    return redirect(_space_url(project, tab='tasks'))


@require_POST
def task_restore(request, pk: int, task_id: int):
    """从归档恢复成顶层任务。"""
    project = project_for(request, pk, write=True)
    task = get_object_or_404(Task, pk=task_id, project=project)
    root = _archive_root(project)
    if root is None or task.parent_id != root.pk:
        return redirect(_space_url(project, tab='tasks'))
    task.parent = None
    task.save(update_fields=['parent'])
    _log_task_action(request, project, task, '从归档恢复', 'task.restore')
    return redirect(_space_url(project, tab='tasks', task=task))
