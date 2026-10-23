"""Session-backed folder grants, bound to the logged-in user.

A grant is only valid while the session belongs to the same user that created
it. Anonymous sessions and grants without a matching ``user_id`` are ignored.
"""

from __future__ import annotations

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
