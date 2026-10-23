"""Project space (T018): activity, plan, tasks, assets and project config.

Reading is owner-or-human-member, exactly like the canvas. Activity notes are
real human messages. Only the owner edits instructions; only the owner with a
project-bound session grant can ask the file service for asset metadata, and
that service never reads file content. Members never receive a folder path or
trigger a filesystem call.
"""

from __future__ import annotations

from pathlib import Path

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from workspaces.grants import context_grant
from workspaces.services import Workspace, WorkspaceError

from projects.board_views import _accessible_project, _visible_projects
from projects.hub_forms import ProjectInstructionsForm, ProjectMessageForm
from projects.models import ProjectMember, ProjectMessage, TaskNode

TABS = ('activity', 'plan', 'tasks', 'assets')
VIEWS = ('table', 'kanban')
OWNER_ONLY = '只有项目所有者可以编辑项目指令。'
MESSAGE_INVALID = '请填写动态内容（最多 4000 字）。'
INSTRUCTIONS_INVALID = '项目指令最多 6000 字，请检查后重试。'

_ASSET_ERRORS = {
    'invalid_root': '项目工作空间当前不可用，请重新授权。',
    'workspace_not_initialized': '项目工作空间当前不可用，请重新授权。',
    'invalid_name': '目录路径无效：不能包含 ..、反斜杠或控制字符。',
    'not_found': '找不到这个目录，可能已被移动或删除。',
    'not_a_directory': '该路径不是文件夹。',
    'unsafe_path': '出于安全考虑，链接、reparse 或隐藏目录不能访问。',
    'read_failed': '读取目录失败，请稍后重试。',
}


def _whitelist(value: str, allowed: tuple[str, ...], default: str) -> str:
    return value if value in allowed else default


def _strict_whitelist(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise Http404('unknown project space option')
    return value


def _asset_error(exc: WorkspaceError) -> str:
    return _ASSET_ERRORS.get(exc.code, '读取目录失败，请稍后重试。')


def _hub(
    request,
    project,
    *,
    tab: str = 'activity',
    view: str = 'table',
    query: str = '',
    status: str = '',
    directory: str = '',
    error: str = '',
    message_form: ProjectMessageForm | None = None,
    instructions_form: ProjectInstructionsForm | None = None,
    status_code: int = 200,
):
    is_owner = project.owner_id == request.user.pk
    all_tasks = list(project.tasks.select_related('assignee', 'parent'))
    visible_tasks = all_tasks
    if tab == 'tasks':
        if query:
            visible_tasks = [
                task for task in visible_tasks
                if query.casefold() in task.title.casefold()
                or query.casefold() in task.description.casefold()
            ]
        if status:
            visible_tasks = [task for task in visible_tasks if task.status == status]

    authorized = is_owner and context_grant(request, project) is not None
    assets: list[dict[str, object]] = []
    asset_root = project.workspace_path if is_owner else ''
    parent_dir = ''
    if tab == 'assets' and is_owner and authorized:
        try:
            assets = Workspace(Path(project.workspace_path)).list_assets(directory)
        except WorkspaceError as exc:
            error = error or _asset_error(exc)
            directory = ''
        except (TypeError, ValueError):
            error = error or _ASSET_ERRORS['invalid_root']
            directory = ''
        parent_dir = directory.rsplit('/', 1)[0] if '/' in directory else ''

    columns = [
        {
            'value': value,
            'label': label,
            'tasks': [task for task in all_tasks if task.status == value],
        }
        for value, label in TaskNode.Status.choices
    ]
    return render(
        request,
        'projects/space.html',
        {
            'project': project,
            'is_owner': is_owner,
            'my_member': project.members.filter(
                kind=ProjectMember.Kind.HUMAN, user=request.user
            ).first(),
            'visible_projects': _visible_projects(request.user).exclude(pk=project.pk),
            'members': list(project.members.all()),
            'ai_members': list(project.members.filter(kind=ProjectMember.Kind.AI)),
            'human_members': list(
                project.members.filter(kind=ProjectMember.Kind.HUMAN)
            ),
            'project_messages': list(
                project.messages.select_related('author').all()[:100]
            ),
            'message_count': project.messages.count(),
            'tasks': visible_tasks,
            'all_task_count': len(all_tasks),
            'columns': columns,
            'active_tab': tab,
            'plan_view': view,
            'query': query,
            'status_filter': status,
            'status_choices': TaskNode.Status.choices,
            'priority_choices': TaskNode.Priority.choices,
            'assets': assets,
            'asset_root': asset_root,
            'authorized': authorized,
            'current_dir': directory,
            'parent_dir': parent_dir,
            'message_form': message_form or ProjectMessageForm(),
            'instructions_form': instructions_form or ProjectInstructionsForm(instance=project),
            'error': error,
            'status_code': status_code,
        },
        status=status_code,
    )


@never_cache
@login_required
@require_GET
def hub(request, pk: int):
    project = _accessible_project(request, pk)
    tab = _strict_whitelist(request.GET.get('tab', 'activity'), TABS)
    view = _strict_whitelist(request.GET.get('view', 'table'), VIEWS)
    query = (request.GET.get('q') or '').strip()[:80]
    status = request.GET.get('status', '')
    if status not in dict(TaskNode.Status.choices):
        status = ''
    directory = request.GET.get('dir', '') if tab == 'assets' else ''
    return _hub(
        request,
        project,
        tab=tab,
        view=view,
        query=query,
        status=status,
        directory=directory,
    )


@never_cache
@login_required
@require_POST
def message_add(request, pk: int):
    project = _accessible_project(request, pk)
    form = ProjectMessageForm(request.POST)
    if not form.is_valid():
        return _hub(
            request, project, tab='activity', message_form=form,
            error=MESSAGE_INVALID, status_code=400,
        )
    ProjectMessage.objects.create(
        project=project, author=request.user, content=form.cleaned_data['content']
    )
    flash.success(request, '已发布动态。')
    return redirect(f"{reverse('projects:hub', args=[project.pk])}?tab=activity")


@never_cache
@login_required
@require_POST
def instructions_update(request, pk: int):
    project = _accessible_project(request, pk)
    if project.owner_id != request.user.pk:
        return _hub(request, project, tab='activity', error=OWNER_ONLY, status_code=403)
    form = ProjectInstructionsForm(request.POST, instance=project)
    if not form.is_valid():
        return _hub(
            request, project, tab='activity', instructions_form=form,
            error=INSTRUCTIONS_INVALID, status_code=400,
        )
    form.save()
    flash.success(request, '已保存项目指令。')
    return redirect(f"{reverse('projects:hub', args=[project.pk])}?tab=activity")
