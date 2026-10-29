"""Roadmap layout: steps run left to right, sub-tasks grow downward.

The X axis is the phase order (step 1, step 2, ...), the Y axis under each step
is its task breakdown. The goal sits at the end of the axis; when every step is
done, the project is done.
"""

from __future__ import annotations

from collections import defaultdict

NODE_WIDTH = 240
NODE_HEIGHT = 96
INDENT = 26
COL_PAD = 14
COL_GAP = 28
ROW = 84
PAD = 28
TOP = 140
STEP_LABEL_Y = 106


def _column_elbow(parent_x: float, parent_y: float, child_x: float, child_y: float, parent_h=NODE_HEIGHT, child_h=NODE_HEIGHT) -> str:
    """Parent above child: drop from the parent, then stub right into the child."""
    spine_x = parent_x + 10
    mid_y = child_y + child_h / 2
    return (
        f'{spine_x:.1f},{parent_y + parent_h:.1f} '
        f'{spine_x:.1f},{mid_y:.1f} '
        f'{child_x:.1f},{mid_y:.1f}'
    )


def _axis_link(x1: float, x2: float) -> str:
    """Straight segment on the X axis, at the vertical centre of the step row."""
    y = TOP + NODE_HEIGHT / 2
    return f'{x1:.1f},{y:.1f} {x2:.1f},{y:.1f}'


def node_height(task):
    return NODE_HEIGHT


def build_tree(tasks) -> dict:
    """Return nodes, links, column panels and canvas size for a task list."""
    tasks = list(tasks)
    children: dict[int | None, list] = defaultdict(list)
    for task in tasks:
        children[task.parent_id].append(task)
    roots = children.get(None, [])

    nodes: list[dict] = []
    links: list[str] = []
    columns: list[dict] = []
    positions: dict[int, tuple[float, float]] = {}

    column_x = PAD
    tallest = 0.0
    root_right_edges: list[float] = []

    for step, root in enumerate(roots, start=1):
        entries: list[tuple[object, int]] = []

        def collect(task, depth: int) -> None:
            entries.append((task, depth))
            for child in children.get(task.pk, []):
                collect(child, depth + 1)

        collect(root, 1)
        max_depth = max(depth for _, depth in entries)
        width = COL_PAD * 2 + NODE_WIDTH + (max_depth - 1) * INDENT
        heights = {task.pk: node_height(task) for task, _ in entries}
        height = sum(heights.values()) + len(entries) * 20 + COL_PAD * 2

        columns.append(
            {
                'x': column_x,
                'y': TOP - COL_PAD,
                'w': width,
                'h': height,
                'step': step,
            }
        )

        y = TOP
        for task, depth in entries:
            x = column_x + COL_PAD + (depth - 1) * INDENT
            positions[task.pk] = (x, y)
            nodes.append(
                {'task': task, 'x': x, 'y': y, 'h': heights[task.pk], 'depth': depth, 'step': step}
            )
            y += heights[task.pk] + 20

        for task, _depth in entries:
            if task.parent_id in positions:
                px, py = positions[task.parent_id]
                cx, cy = positions[task.pk]
                links.append(_column_elbow(px, py, cx, cy, heights[task.parent_id], heights[task.pk]))

        root_right_edges.append(column_x + COL_PAD + NODE_WIDTH)
        column_x += width + COL_GAP
        tallest = max(tallest, height)

    content_width = (column_x - COL_GAP) if roots else PAD + NODE_WIDTH
    goal_x = content_width + 56 if roots else PAD
    goal_y = TOP
    total_width = goal_x + NODE_WIDTH + PAD
    height = (TOP + tallest + PAD) if roots else TOP + NODE_HEIGHT + PAD

    for index, root in enumerate(roots):
        rx, _ry = positions[root.pk]
        if index + 1 < len(roots):
            next_root_x = positions[roots[index + 1].pk][0]
            links.append(_axis_link(rx + NODE_WIDTH, next_root_x))
        else:
            links.append(_axis_link(root_right_edges[-1], goal_x))

    return {
        'nodes': nodes,
        'links': links,
        'columns': columns,
        'goal': {'x': goal_x, 'y': goal_y, 'h': NODE_HEIGHT},
        'width': total_width,
        'height': height,
        'rows': len(nodes),
        'step_y': STEP_LABEL_Y,
    }
