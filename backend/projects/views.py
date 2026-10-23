"""Owner-scoped project pages and explicit workspace association (T012B).

The project only remembers where its folder lives. Opening a project never
authorizes file access: the user must still authorize the associated folder in
the workspace page, and that grant is bound to both user and project.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from workspaces.grants import context_grant, get_grant, same_path, set_grant
from workspaces.services import Workspace, WorkspaceError

from projects.forms import ProjectForm
from projects.models import Project, ProjectMember

NO_GRANT = '当前未授权任何文件夹。请先到工作区选择并授权一个文件夹，再回来关联。'
INVALID_ROOT = '该文件夹当前不可用（需为已存在的普通目录，不能是链接、UNC 或设备路径）。'
NO_PATH = '请先关联一个已授权的文件夹，再打开项目工作区。'


def _owned(request, pk: int) -> Project:
    return get_object_or_404(Project, pk=pk, owner=request.user)


def _grant_root(request) -> str | None:
    grant = get_grant(request)
    return grant['root'] if grant else None


def _grant_project(request, grant: dict[str, str] | None) -> Project | None:
    """Resolve the project a grant is bound to, scoped to the current user."""
    project_id = grant['project_id'] if grant else ''
    if (
        not project_id.isascii() or not project_id.isdecimal()
        or len(project_id) > 19 or int(project_id) <= 0
    ):
        return None
    return Project.objects.filter(pk=int(project_id), owner=request.user).first()


def _detail_context(request, project, grant, error: str = '') -> dict:
    return {
        'project': project,
        'grant_root': grant['root'] if grant else '',
        'grant_project_id': grant['project_id'] if grant else '',
        'authorized': context_grant(request, project) is not None,
        'grant_differs': bool(
            grant
            and project.workspace_path
            and not same_path(grant['root'], project.workspace_path)
        ),
        'error': error,
    }


@never_cache
@login_required
def project_list(request):
    projects = list(Project.objects.filter(owner=request.user))
    grant = get_grant(request)
    grant_project = _grant_project(request, grant)
    grant_usable = context_grant(request, grant_project) is not None
    for project in projects:
        project.authorized = context_grant(request, project) is not None
        # Only offer the explicit POST association when it cannot silently move
        # an existing project to a different folder.
        project.can_link_grant = (
            grant_usable
            and not project.authorized
            and (
                not project.workspace_path
                or same_path(project.workspace_path, grant['root'])
            )
        )
    return render(
        request,
        'projects/list.html',
        {
            'projects': projects,
            'grant': grant,
            'grant_project': grant_project,
            'grant_usable': grant_usable,
        },
    )


@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def project_new(request):
    grant_root = _grant_root(request)
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        link = request.POST.get('link_grant') == 'on'
        error = ''
        if form.is_valid():
            if link:
                if not grant_root:
                    error = NO_GRANT
                else:
                    try:
                        Workspace(Path(grant_root)).validate_root()
                    except (WorkspaceError, TypeError, ValueError):
                        error = INVALID_ROOT
            if not error:
                # The owner becomes the first human member in the same
                # transaction, so a project never exists without its owner row.
                with transaction.atomic():
                    project = form.save(commit=False)
                    project.owner = request.user
                    project.workspace_path = str(Path(grant_root)) if link and grant_root else ''
                    project.save()
                    ProjectMember.objects.create(
                        project=project,
                        kind=ProjectMember.Kind.HUMAN,
                        name=request.user.username,
                        role='项目负责人',
                        user=request.user,
                    )
                messages.success(request, f'已创建项目：{project.name}')
                return redirect('projects:board', pk=project.pk)
        return render(
            request,
            'projects/new.html',
            {'form': form, 'grant_root': grant_root, 'error': error,
             'linked': link},
            status=400,
        )
    return render(
        request,
        'projects/new.html',
        {'form': ProjectForm(), 'grant_root': grant_root, 'error': '', 'linked': True},
    )


@never_cache
@login_required
def project_detail(request, pk: int):
    project = _owned(request, pk)
    return render(
        request, 'projects/detail.html', _detail_context(request, project, get_grant(request))
    )


@never_cache
@login_required
@require_POST
def project_link_workspace(request, pk: int):
    project = _owned(request, pk)
    grant = get_grant(request)
    if not grant:
        return render(
            request,
            'projects/detail.html',
            _detail_context(request, project, None, NO_GRANT),
            status=400,
        )
    try:
        Workspace(Path(grant['root'])).validate_root()
    except (WorkspaceError, TypeError, ValueError):
        return render(
            request,
            'projects/detail.html',
            _detail_context(request, project, grant, INVALID_ROOT),
            status=400,
        )
    project.workspace_path = str(Path(grant['root']))
    project.save(update_fields=['workspace_path', 'updated_at'])
    # Re-bind the current grant to this project and rotate its id so pages
    # rendered before the association can no longer write.
    set_grant(request, project.workspace_path, uuid.uuid4().hex, project_id=str(project.pk))
    messages.success(request, f'已关联文件夹到项目：{project.name}')
    return redirect('projects:detail', pk=project.pk)


@never_cache
@login_required
def project_open(request, pk: int):
    project = _owned(request, pk)
    if not project.workspace_path:
        messages.info(request, NO_PATH)
        return redirect('projects:detail', pk=project.pk)
    return redirect(f'/workspace/?project={project.pk}')
