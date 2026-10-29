"""Keep parent stage status in sync with its children.

The timeline header must never drift from the cards below it, so the
derivation lives here and is reused by both the view and the signals.
"""

from __future__ import annotations

from .models import Task


def fold(statuses: list[str], fallback: str, sticky: bool = False) -> str:
    """Fold child statuses into one stage status.

    ``sticky`` marks a stage that someone blocked on purpose (it carries a
    reason); that verdict outlives "all cards are done". Blocked inherited
    from a child is not sticky and can roll back to done.
    """
    if sticky and fallback == Task.Status.BLOCKED:
        return Task.Status.BLOCKED
    if not statuses:
        return fallback
    if all(value == Task.Status.DONE for value in statuses):
        return Task.Status.DONE
    if all(value == Task.Status.TODO for value in statuses):
        return Task.Status.TODO
    if any(value == Task.Status.BLOCKED for value in statuses):
        return Task.Status.BLOCKED
    return Task.Status.DOING


def is_blocked_on_purpose(node: Task) -> bool:
    """True when the node itself carries a blocker, not one inherited."""
    return node.status == Task.Status.BLOCKED and bool(
        node.blocked_reason or node.unblock_action
    )


def subtree_status(node: Task) -> str:
    """Status of ``node`` derived from its whole subtree."""
    children = list(node.children.all())
    if not children:
        return node.status
    return fold(
        [subtree_status(child) for child in children],
        node.status,
        is_blocked_on_purpose(node),
    )


def refresh_parents(task: Task) -> None:
    """Recompute every ancestor of ``task``, bottom-up, until stable."""
    node = task
    guard = 0
    while node.parent_id and guard < 20:
        guard += 1
        # Always read the parent fresh: the in-memory copy may hold a stale status.
        parent = Task.objects.filter(pk=node.parent_id).first()
        if parent is None:
            return
        resolved = subtree_status(parent)
        if resolved == parent.status:
            return
        Task.objects.filter(pk=parent.pk).update(status=resolved)
        node = parent
