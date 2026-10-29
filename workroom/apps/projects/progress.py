"""Read-only milestone summaries from existing task structure and delivery state."""

from collections import Counter, defaultdict

from django.utils import timezone

from .task_explanations import explanation

LABELS = {
    "done": "已完成",
    "pending": "待本人确认",
    "returned": "待修改",
    "blocked": "需处理阻碍",
    "doing": "进行中",
    "todo": "待开始",
}


def _stats(rows):
    counts = dict.fromkeys(LABELS, 0)
    counts.update(Counter(row["category"] for row in rows))
    total = len(rows)
    return dict(total=total, counts=counts, percent=counts["done"] * 100 // total if total else 0)


def summarize(tasks, today=None):
    """Caller supplies ordered, related/prefetched tasks; never saves or queries."""
    tasks = list(tasks)
    today = today or timezone.localdate()
    children = defaultdict(list)
    for task in tasks:
        children[task.parent_id].append(task)
    hidden = set()
    stack = [task for task in tasks if task.parent_id is None and task.title.startswith("归档")]
    while stack:
        task = stack.pop()
        if task.pk not in hidden:
            hidden.add(task.pk)
            stack.extend(children[task.pk])
    active = [task for task in tasks if task.pk not in hidden]
    by_id = {task.pk: task for task in active}

    def row(task):
        records = list(task.deliveries.all())
        latest = max(records, key=lambda record: record.pk) if records else None
        readable = explanation(task, children=children[task.pk], latest_delivery=latest)
        if latest and latest.status in {"pending", "returned"}:
            category = latest.status
        elif task.status == "done":
            category = "done"
        elif readable["blockers"]:
            category = "blocked"
        else:
            category = "doing" if task.status == "doing" else "todo"
        if category == "returned" and not any(b["kind"] == "returned" for b in readable["blockers"]):
            readable["blockers"].append(dict(kind="returned", text="上次交付被退回：" + latest.review_note,
                                             action="按退回意见修改，再提交新的交付。"))
            readable["next_action"] = "按退回意见修改，再提交新的交付。"
        return dict(task=task, delivery=latest, readable=readable, category=category,
                    label=LABELS[category], overdue=bool(task.end_date and task.end_date < today and category != "done"))

    leaves = [row(task) for task in active if not children[task.pk]]
    rows_by_id = {item["task"].pk: item for item in leaves}
    roots = [task for task in active if task.parent_id not in by_id]
    containers = [task for task in roots if children[task.pk]]
    # A single overall goal containing stage containers is not itself a stage.
    if len(roots) == 1 and containers:
        nested = [task for task in children[containers[0].pk] if children[task.pk]]
        if nested:
            containers = nested
    stages = []
    grouped = set()
    for task in containers:
        descendants = set()
        stack = list(children[task.pk])
        while stack:
            child = stack.pop()
            if child.pk not in descendants:
                descendants.add(child.pk)
                stack.extend(children[child.pk])
        items = [item for item in leaves if item["task"].pk in descendants]
        grouped.update(item["task"].pk for item in items)
        own = row(task)
        stats = _stats(items)
        if task.blocked_reason.strip():
            label = "需处理阶段问题"
        elif stats["total"] and stats["counts"]["done"] == stats["total"]:
            label = "阶段已记录完成" if own["category"] == "done" else "子任务完成，阶段待确认"
        elif stats["counts"]["pending"] or own["category"] == "pending":
            label = "有交付待本人确认"
        elif stats["counts"]["blocked"] or stats["counts"]["returned"]:
            label = "有任务需处理"
        elif stats["counts"]["doing"] or stats["counts"]["done"]:
            label = "进行中"
        else:
            label = "待开始"
        stages.append(dict(**stats, task=task, title=task.title, rows=items,
                           readable=own["readable"], own=own, label=label, overdue=own["overdue"]))
    loose = [item for item in leaves if item["task"].pk not in grouped]
    if loose:
        stages.append(dict(**_stats(loose), task=None, title="未分阶段的任务", rows=loose,
                           readable=None, own=None, label="按实际任务状态汇总", overdue=False))

    action = None
    for category, kind, label in [("pending", "review", "先核对交付"), ("returned", "revise", "按退回意见修改")]:
        candidates = leaves + [s["own"] for s in stages if s["own"]]
        candidate = next((item for item in candidates if item["category"] == category), None)
        if candidate:
            action = dict(kind=kind, label=label, row=candidate,
                          description="打开交付记录，核对结果后确认或退回。" if kind == "review" else candidate["readable"]["next_action"])
            break
    if action is None:
        parent_issue = next((s for s in stages if s["task"] and s["task"].blocked_reason.strip()), None)
        if parent_issue:
            action = dict(kind="stage", label="处理阶段问题", row=parent_issue["own"], description=parent_issue["readable"]["next_action"])
    if action is None:
        for category in ["doing", "todo", "blocked"]:
            candidate = next((item for item in leaves if item["category"] == category), None)
            if candidate:
                action = dict(kind="blocked" if category == "blocked" else "task",
                              label="先处理阻碍" if category == "blocked" else ("继续这项任务" if category == "doing" else "从这项开始"),
                              row=candidate, description=candidate["readable"]["next_action"])
                break
    if action is None:
        unfinished_stage = next((s for s in stages if s["own"] and s["own"]["category"] != "done"), None)
        if unfinished_stage:
            action = dict(kind="stage", label="核对阶段结果", row=unfinished_stage["own"], description="具体任务已完成，请核对阶段目标和验收要求，再记录阶段结果。")
    for index, stage in enumerate(stages):
        target = action["row"]["task"].pk if action else None
        stage["expanded"] = bool(target in {item["task"].pk for item in stage["rows"]} or (stage["task"] and stage["task"].pk == target)) if action else index == 0
    return dict(**_stats(leaves), stages=stages, next=action, archived_count=len(hidden), rows=rows_by_id)
