"""Central project permission rules.

Local mode deliberately keeps the historical anonymous single-user behaviour;
server mode never trusts a login alone and always checks the project role.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import AuditLog, Project, ProjectMembership

ROLE_LEVEL = {
    ProjectMembership.Role.VIEWER: 1,
    ProjectMembership.Role.EDITOR: 2,
    ProjectMembership.Role.OWNER: 3,
}


def is_server() -> bool:
    return getattr(settings, 'WORKROOM_MODE', 'local') == 'server'


def membership_for(user, project: Project) -> ProjectMembership | None:
    if not getattr(user, 'is_authenticated', False):
        return None
    return ProjectMembership.objects.filter(project=project, user=user).first()


def role_of(user, project: Project) -> str:
    membership = membership_for(user, project)
    return membership.role if membership else ''


def project_for(
    request,
    pk: int,
    *,
    write: bool = False,
    owner: bool = False,
) -> Project:
    """Return the project or raise 404/403.

    Non-members get 404 (do not reveal that a project exists); members without
    enough role get 403. Local mode keeps the old anonymous access.
    """
    project = get_object_or_404(Project, pk=pk)
    if not is_server():
        return project
    membership = membership_for(request.user, project)
    if membership is None:
        raise Http404('project not found')
    if owner and membership.role != ProjectMembership.Role.OWNER:
        raise PermissionDenied('需要项目所有者权限。')
    if write and ROLE_LEVEL.get(membership.role, 0) < ROLE_LEVEL[
        ProjectMembership.Role.EDITOR
    ]:
        raise PermissionDenied('只读成员不能修改项目。')
    return project


def visible_projects(user):
    if not is_server():
        return Project.objects.all()
    return Project.objects.filter(memberships__user=user).distinct()


def audit(project, user, action: str, detail: str = '') -> AuditLog:
    return AuditLog.objects.create(
        project=project,
        actor_user=user if getattr(user, 'is_authenticated', False) else None,
        action=action,
        detail=detail[:4000],
    )
