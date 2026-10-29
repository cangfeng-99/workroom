"""Validate a model-produced task draft before it reaches the tree."""

from __future__ import annotations

from datetime import date, timedelta

from .models import Task

MAX_TASKS = 15
MAX_DEPTH = 5
MAX_TITLE = 160
MAX_DETAIL = 4000


class PlanError(Exception):
    """A user-facing reason why the model output cannot be used."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def dependency_refs(rows) -> dict[str, list[str]]:
    """Validate same-draft references before any task writes; old drafts work."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PlanError('草稿任务格式不正确，请重新生成草稿。')
    graph = {}
    requested = False
    for row in rows:
        ref = str(row.get('ref') or '').strip()
        raw = row.get('prerequisite_refs')
        if raw is None:
            raw = []
        if not isinstance(raw, list) or any(not isinstance(value, str) or not value.strip() for value in raw):
            raise PlanError('前置任务需要使用任务编号数组，每个编号都不能为空。')
        values = list(dict.fromkeys(value.strip() for value in raw))
        requested = requested or bool(values)
        graph[ref] = values
    if not requested:
        return graph
    refs = [str(row.get('ref') or '').strip() for row in rows]
    if len(rows) > MAX_TASKS or not all(refs) or len(set(refs)) != len(refs):
        raise PlanError('带前置关系的草稿最多15项，每项都需要唯一任务编号。')
    parents_seen = set()
    for row, ref in zip(rows, refs):
        parent = row.get('parent_ref')
        if parent and (not isinstance(parent, str) or parent.strip() not in parents_seen):
            raise PlanError('草稿的父任务编号不存在或顺序不正确，请重新生成。')
        parents_seen.add(ref)
        for required in graph[ref]:
            if required not in graph:
                raise PlanError(f'前置任务「{required[:80]}」不在这份草稿中，请核对任务编号。')
            if required == ref:
                raise PlanError('任务不能把自己作为前置任务。')
    visiting, visited = set(), set()

    def visit(ref):
        if ref in visiting:
            raise PlanError('前置关系形成了循环，请先修正先后顺序。')
        if ref in visited:
            return
        visiting.add(ref)
        for required in graph[ref]:
            visit(required)
        visiting.remove(ref)
        visited.add(ref)

    for ref in graph:
        visit(ref)
    return graph


def preview_draft(rows):
    """Present names for review without trusting malformed saved references."""
    titles = {str(row.get('ref') or '').strip(): str(row.get('title') or '未命名任务') for row in rows if isinstance(row, dict)}
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        required = row.get('prerequisite_refs')
        if required is None:
            required = []
        if isinstance(required, list) and all(isinstance(ref, str) for ref in required):
            item['prerequisite_titles'] = [titles.get(ref.strip(), f'引用未找到：{ref[:80]}') for ref in dict.fromkeys(required)]
        else:
            item['prerequisite_titles'] = ['前置关系格式有误，请重新生成草稿。']
        result.append(item)
    return result


def _parse_date(value, start: date, end: date, label: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PlanError(f'「{label}」的日期格式不对，应为 YYYY-MM-DD。') from exc
    if parsed < start or parsed > end:
        raise PlanError(f'「{label}」的日期超出了项目起止范围。')
    return parsed


def window(project) -> tuple[date, date]:
    """The date range a plan must stay inside."""
    start = date.today()
    end = project.goal_deadline or start + timedelta(days=14)
    if end < start:
        end = start + timedelta(days=14)
    return start, end


def validate(payload, members, start: date, end: date) -> list[dict]:
    if not isinstance(payload, dict):
        raise PlanError('模型返回的不是 JSON 对象。')
    raw = payload.get('tasks')
    if not isinstance(raw, list) or not raw:
        raise PlanError('模型没有返回任务列表。')
    if len(raw) > MAX_TASKS:
        raise PlanError(f'任务超过 {MAX_TASKS} 个，请缩小目标范围后重试。')

    dependencies = dependency_refs(raw)
    member_ids = {member.pk for member in members}
    depths: dict[str, int] = {}
    seen: set[str] = set()
    tasks: list[dict] = []

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PlanError('任务格式不对，应为对象。')
        ref = str(item.get('ref') or '').strip()
        if not ref or ref in seen:
            raise PlanError('任务标识缺失或重复。')
        parent_ref = item.get('parent_ref')
        if parent_ref in ('', None):
            parent_ref = None
        if index == 0:
            if parent_ref is not None:
                raise PlanError('第一个任务必须是根任务。')
            depth = 1
        else:
            if parent_ref is None or parent_ref not in depths:
                raise PlanError('有任务引用了不存在或更靠后的父任务。')
            depth = depths[parent_ref] + 1
        if depth > MAX_DEPTH:
            raise PlanError(f'任务层级超过 {MAX_DEPTH} 层。')

        title = str(item.get('title') or '').strip()
        if not title:
            raise PlanError('有任务缺少标题。')
        if len(title) > MAX_TITLE:
            raise PlanError(f'任务标题超过 {MAX_TITLE} 字。')
        detail = str(item.get('detail') or item.get('description') or '')
        if len(detail) > MAX_DETAIL:
            raise PlanError(f'任务内容超过 {MAX_DETAIL} 字。')

        start_at = _parse_date(item.get('start_date'), start, end, title)
        end_at = _parse_date(item.get('end_date'), start, end, title)
        if end_at < start_at:
            raise PlanError(f'「{title}」的结束日期早于开始日期。')

        assignee_id = item.get('assignee_id')
        if assignee_id in ('', None):
            assignee_id = None
        else:
            try:
                assignee_id = int(assignee_id)
            except (TypeError, ValueError):
                assignee_id = None
            if assignee_id not in member_ids:
                assignee_id = None

        priority = item.get('priority')
        if priority not in dict(Task.Priority.choices):
            priority = Task.Priority.NORMAL

        seen.add(ref)
        depths[ref] = depth
        why = str(item.get('why') or '').strip()[:500]
        outcome = str(item.get('outcome') or '').strip()[:500]
        estimate = str(item.get('estimate') or '').strip()[:40]
        acceptance = str(item.get('acceptance') or '').strip()[:2000]
        guide = item.get('guide') if isinstance(item.get('guide'), dict) else {}
        raw_spec = item.get('execution_spec')
        spec = {}
        if isinstance(raw_spec, dict):
            for key in ('work_kind', 'workspace_key', 'baseline', 'risk',
                        'allowed_paths', 'relevant_files', 'check_commands'):
                if key in raw_spec:
                    spec[key] = raw_spec[key]
        tasks.append(
            {
                'ref': ref,
                'parent_ref': parent_ref,
                'prerequisite_refs': dependencies.get(ref, []),
                'title': title,
                'detail': detail,
                'assignee_id': assignee_id,
                'start_date': start_at.isoformat(),
                'end_date': end_at.isoformat(),
                'priority': priority,
                'why': why,
                'outcome': outcome,
                'estimate': estimate,
                'acceptance': acceptance,
                'guide': guide,
                'execution_spec': spec,
            }
        )

    roots = [task for task in tasks if task['parent_ref'] is None]
    if len(roots) != 1:
        raise PlanError('必须且只能有一个根任务，代表项目目标下的第一层。')
    return tasks
