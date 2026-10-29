"""Dependency chain around one task: what blocks it, what it blocks.

Borrowed from archify's "route tracing": a focused node should light up the
path that reaches it and the path that leaves it, instead of showing a static
list of boxes.
"""

from __future__ import annotations

from .models import Task


def edges(project) -> list[tuple[int, int]]:
    """Return (task_id, prerequisite_id) pairs for one project."""
    through = Task.prerequisites.through
    return list(
        through.objects.filter(from_task__project=project).values_list(
            'from_task_id', 'to_task_id'
        )
    )


def build(project, focus_id: int, depth: int = 8) -> dict:
    """Collect upstream/downstream ids plus the edges among them."""
    pairs = edges(project)
    up_map: dict[int, list[int]] = {}
    down_map: dict[int, list[int]] = {}
    for task_id, prereq_id in pairs:
        up_map.setdefault(task_id, []).append(prereq_id)
        down_map.setdefault(prereq_id, []).append(task_id)

    def walk(start: int, graph: dict[int, list[int]]) -> list[int]:
        seen: list[int] = []
        queue = [(start, 0)]
        visited = {start}
        while queue:
            node, level = queue.pop(0)
            if level >= depth:
                continue
            for nxt in graph.get(node, []):
                if nxt in visited:
                    continue
                visited.add(nxt)
                seen.append(nxt)
                queue.append((nxt, level + 1))
        return seen

    upstream = walk(focus_id, up_map)
    downstream = walk(focus_id, down_map)
    involved = {focus_id, *upstream, *downstream}
    links = [
        (task_id, prereq_id)
        for task_id, prereq_id in pairs
        if task_id in involved and prereq_id in involved
    ]
    return {
        'focus': focus_id,
        'upstream': upstream,
        'downstream': downstream,
        'links': links,
        'size': len(involved),
    }
