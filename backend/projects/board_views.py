"""Project board: team, task tree, canvas data and explicit folder authorization.

Reading is allowed for the owner and for human members of that project. Only
the owner manages members, task structure, assignments, dates and the
workspace; a member may only change the status of a task assigned to them.
Members never receive the owner's folder path or any file permission.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from workspaces.grants import set_grant
from workspaces.services import Workspace, WorkspaceError

from projects.board_forms import (
    MemberForm,
    MemberUpdateForm,
    TaskForm,
    TaskStatusForm,
    WorkspaceForm,
)
from projects.models import Project, ProjectMember, TaskNode

OWNER_ONLY = '只有项目所有者可以管理成员、任务结构和工作空间。'
INVALID_ROOT = '该文件夹当前不可用（需为已存在的普通目录，不能是链接、UNC 或设备路径）。'
MEMBER_DUPLICATE = '该账号已经是本项目成员。'


def _accessible_project(request, pk: int) -> Project:
    """Owner or human member; every other account gets a plain 404."""
    project = (
        Project.objects.filter(pk=pk)
        .filter(
            Q(owner=request.user)
            | Q(members__user=request.user, members__kind=ProjectMember.Kind.HUMAN)
        )
        .distinct()
        .first()
    )
    if project is None:
        raise Http404('project not found')
    return project


def _find_member(request, project: Project) -> ProjectMember | None:
    return project.members.filter(
        kind=ProjectMember.Kind.HUMAN, user=request.user
    ).first()


def _canvas_data(project: Project) -> dict:
    """Plain data for the canvas; no paths, grants or HTML."""
    members = list(project.members.all())
    tasks = list(project.tasks.select_related('assignee').all())
    return {
        'project': {
            'id': project.pk,
            'name': project.name,
            'description': project.description,
        },
        'members': [
            {'id': member.pk, 'name': member.name, 'kind': member.kind, 'role': member.role}
            for member in members
        ],
        'tasks': [
            {
                'id': task.pk,
                'parent_id': task.parent_id,
                'title': task.title,
                'description': task.description,
                'status': task.status,
                'status_label': task.get_status_display(),
                'assignee_id': task.assignee_id,
                'assignee_name': task.assignee.name if task.assignee else '',
                'start_date': task.start_date.isoformat(),
                'end_date': task.end_date.isoformat(),
            }
            for task in tasks
        ],
    }


def _board(
    request,
    project: Project,
    *,
    status: int = 200,
    error: str = '',
    task_form: TaskForm | None = None,
    member_form: MemberForm | None = None,
    workspace_form: WorkspaceForm | None = None,
    editing_task: TaskNode | None = None,
    edit_form=None,
    notice: str = '',
):
    is_owner = project.owner_id == request.user.pk
    member = _find_member(request, project)
    if not is_owner:
        # A member never sees the owner's folder path, grant or workspace form.
        workspace_form = None
    return render(
        request,
        'projects/board.html',
        {
            'project': project,
            'is_owner': is_owner,
            'my_member': member,
            'visible_projects': _visible_projects(request.user),
            'members': list(project.members.all()),
            'tasks': list(project.tasks.select_related('assignee').all()),
            'task_form': task_form or (TaskForm(project=project) if is_owner else None),
            'member_form': member_form or (MemberForm(project=project) if is_owner else None),
            'workspace_form': workspace_form
            or (WorkspaceForm() if is_owner else None),
            'editing_task': editing_task,
            'edit_form': edit_form,
            'status_choices': TaskNode.Status.choices,
            'canvas_data': _canvas_data(project),
            'error': error,
            'notice': notice,
        },
        status=status,
    )


def _visible_projects(user):
    return (
        Project.objects.filter(
            Q(owner=user) | Q(members__user=user, members__kind=ProjectMember.Kind.HUMAN)
        )
        .distinct()
        .order_by('-updated_at', '-pk')
    )


def _owner_only(request, project: Project, **kwargs):
    if project.owner_id != request.user.pk:
        return _board(request, project, status=403, error=OWNER_ONLY, **kwargs)
    return None


@never_cache
@login_required
@require_GET
def board(request, pk: int):
    project = _accessible_project(request, pk)
    is_owner = project.owner_id == request.user.pk
    member = _find_member(request, project)
    editing_task = None
    edit_form = None

    raw_task = request.GET.get('task')
    if raw_task is not None:
        if not raw_task.isascii() or not raw_task.isdecimal() or len(raw_task) > 19:
            raise Http404('invalid task')
        editing_task = get_object_or_404(TaskNode, pk=int(raw_task), project=project)
        if is_owner:
            edit_form = TaskForm(
                instance=editing_task, project=project, include_parent=False
            )
        elif member is not None and editing_task.assignee_id == member.pk:
            edit_form = TaskStatusForm(instance=editing_task)

    return _board(
        request,
        project,
        editing_task=editing_task,
        edit_form=edit_form,
    )


@never_cache
@login_required
@require_POST
def member_add(request, pk: int):
    project = _accessible_project(request, pk)
    denied = _owner_only(request, project)
    if denied is not None:
        return denied
    form = MemberForm(request.POST, project=project)
    if not form.is_valid():
        return _board(
            request, project, status=400, error='请检查成员信息。', member_form=form
        )
    kind = form.cleaned_data['kind']
    try:
        with transaction.atomic():
            ProjectMember.objects.create(
                project=project,
                kind=kind,
                name=form.cleaned_data['name'],
                role=form.cleaned_data['role'],
                user=form.cleaned_data['user'],
            )
    except IntegrityError:
        return _board(
            request, project, status=400, error=MEMBER_DUPLICATE,
            member_form=MemberForm(project=project),
        )
    messages.success(request, f'已添加成员：{form.cleaned_data["name"]}')
    return redirect('projects:board', pk=project.pk)


@never_cache
@login_required
@require_POST
def member_update(request, pk: int, member_pk: int):
    project = _accessible_project(request, pk)
    denied = _owner_only(request, project)
    if denied is not None:
        return denied
    member = get_object_or_404(ProjectMember, pk=member_pk, project=project)
    form = MemberUpdateForm(request.POST, instance=member)
    if not form.is_valid():
        return _board(request, project, status=400, error='请检查角色。')
    form.save()
    messages.success(request, f'已更新角色：{member.name}')
    return redirect('projects:board', pk=project.pk)


@never_cache
@login_required
@require_POST
def task_add(request, pk: int):
    project = _accessible_project(request, pk)
    denied = _owner_only(request, project)
    if denied is not None:
        return denied
    form = TaskForm(request.POST, project=project)
    if not form.is_valid():
        return _board(
            request, project, status=400, error='请检查任务内容与日期。', task_form=form
        )
    task = form.save(commit=False)
    task.project = project
    task.save()
    messages.success(request, f'已创建任务：{task.title}')
    return redirect('projects:board', pk=project.pk)


@never_cache
@login_required
@require_POST
def task_update(request, pk: int, task_pk: int):
    project = _accessible_project(request, pk)
    task = get_object_or_404(TaskNode, pk=task_pk, project=project)
    is_owner = project.owner_id == request.user.pk

    if is_owner:
        form = TaskForm(request.POST, instance=task, project=project, include_parent=False)
    else:
        member = _find_member(request, project)
        if member is None or task.assignee_id != member.pk:
            return _board(
                request, project, status=403,
                error='只能更新分配给自己任务的进度状态。',
            )
        # Members get a status-only form; any other posted field is ignored.
        form = TaskStatusForm(request.POST, instance=task)

    if not form.is_valid():
        return _board(
            request,
            project,
            status=400,
            error='请检查填写内容。',
            editing_task=task,
            edit_form=form,
        )
    form.save()
    messages.success(request, f'已更新任务：{task.title}')
    if is_owner:
        return redirect(f'/projects/{project.pk}/board/?task={task.pk}')
    return redirect('projects:board', pk=project.pk)


@never_cache
@login_required
@require_POST
def board_workspace(request, pk: int):
    project = _accessible_project(request, pk)
    denied = _owner_only(request, project)
    if denied is not None:
        return denied
    form = WorkspaceForm(request.POST)
    if not form.is_valid():
        return _board(
            request, project, status=400, error='请填写文件夹完整路径。', workspace_form=form
        )
    path = form.cleaned_data['path']
    try:
        Workspace(Path(path)).validate_root()
    except (WorkspaceError, TypeError, ValueError):
        # Keep the previous location and grant untouched on any invalid input.
        return _board(
            request, project, status=400, error=INVALID_ROOT, workspace_form=form
        )
    project.workspace_path = str(Path(path))
    project.save(update_fields=['workspace_path', 'updated_at'])
    set_grant(request, project.workspace_path, uuid.uuid4().hex, project_id=str(project.pk))
    messages.success(request, f'已授权并设为工作空间：{project.name}')
    return redirect('projects:board', pk=project.pk)
