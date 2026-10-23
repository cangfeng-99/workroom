"""Session-backed folder grants, bound to the logged-in user.

A grant is only valid while the session belongs to the same user that created
it. Anonymous sessions and grants without a matching ``user_id`` are ignored.
"""

from __future__ import annotations

import os

SESSION_KEY = 'workspace_grant_v2'
LEGACY_SESSION_KEY = 'workspace_grant_root'


def get_grant(request) -> dict[str, str] | None:
    """Return the current user's grant, or ``None`` if absent or foreign."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return None
    data = request.session.get(SESSION_KEY)
    if not isinstance(data, dict):
        return None
    root = data.get('root')
    grant_id = data.get('grant_id')
    user_id = data.get('user_id')
    project_id = data.get('project_id', '')
    if not isinstance(root, str) or not root:
        return None
    if not isinstance(grant_id, str) or not grant_id:
        return None
    if not isinstance(project_id, str):
        return None
    if str(user_id) != str(user.pk):
        return None
    return {
        'root': root,
        'grant_id': grant_id,
        'user_id': str(user.pk),
        'project_id': project_id,
    }


def set_grant(request, root: str, grant_id: str, project_id: str = '') -> None:
    request.session[SESSION_KEY] = {
        'root': root,
        'grant_id': grant_id,
        'user_id': str(request.user.pk),
        'project_id': project_id,
    }


def clear_grant(request) -> None:
    request.session.pop(SESSION_KEY, None)
    request.session.pop(LEGACY_SESSION_KEY, None)


def same_path(left: str, right: str) -> bool:
    """Compare two local paths the same way for every page and view."""
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def context_grant(request, project=None) -> dict[str, str] | None:
    """Return only the grant that belongs to this exact context.

    ``project is None`` is the independent workspace: only a grant with an
    empty ``project_id`` counts. A project context additionally requires the
    grant to be bound to that project and rooted at its remembered folder, so
    a standalone grant or another folder's grant can never mark it authorized.
    """
    grant = get_grant(request)
    if not grant:
        return None
    if project is None:
        return None if grant['project_id'] else grant
    if grant['project_id'] != str(project.pk):
        return None
    if not project.workspace_path or not same_path(grant['root'], project.workspace_path):
        return None
    return grant
