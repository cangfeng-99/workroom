"""Read-only agent loop: observe the project, then produce a plan.

The loop is deliberately simple and provider-agnostic: every step the model must
return one JSON action, we execute it locally, append the observation, and ask
again. No writes, no shell — execution belongs to external agents later.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from . import agent_tools, ai_client

MAX_STEPS = 6

SYSTEM = (
    '你是一个只读的工程 Agent，帮项目负责人看清现状并制定计划。'
    '你可以调用三个只读工具：list_dir{path}、read_file{path}、search{query,path}。'
    f'允许访问的根目录是 {agent_tools.root()}，所有路径都相对于它。'
    '每一步只输出一个 JSON 对象，不要 Markdown、不要解释：'
    '{"thought":"一句话说明为什么调这个工具","tool":"list_dir|read_file|search|finish","args":{"path":"..."}}。'
    '结束时不调用工具，输出 {"thought":"...","tool":"finish","answer":"中文计划"}。'
    'answer 必须包含：你理解的目标、读到的项目现状（引用真实文件名）、分步计划、风险。'
    '不要编造没有读到的内容；最多 6 步；找不到就说找不到。'
)


def _context(project, tasks, library) -> str:
    lines = [f'项目：{project.name}', f'目标：{project.goal_title}']
    if project.goal_detail:
        lines.append(f'说明：{project.goal_detail}')
    if tasks:
        lines.append('当前任务：' + '；'.join(task.title for task in tasks[:12]))
    if library:
        lines.append('项目资料库（规则与已定决策，计划必须遵守）：')
        for entry in library[:6]:
            text = (entry.summary or entry.body or '').strip()
            text = text.replace(chr(10), ' ')
            if len(text) > 300:
                text = text[:300] + '…'
            suffix = f'：{text}' if text else ''
            lines.append(f'- [{entry.kind_label}] {entry.title}{suffix}')
    return '\n'.join(lines)


def _run_tool(tool: str, args: dict) -> str:
    if tool not in agent_tools.TOOLS:
        return '未知工具。可用：list_dir / read_file / search / finish。'
    clean = {
        key: str(value)[:300]
        for key, value in args.items()
        if key in {'path', 'query'} and isinstance(value, (str, int, float))
    }
    try:
        if tool == 'search':
            return agent_tools.search(
                clean.get('query', ''), clean.get('path', '.')
            )
        return agent_tools.TOOLS[tool](clean.get('path', '.'))
    except agent_tools.ToolError as exc:
        return f'工具出错：{exc.message}'
    except TypeError:
        return '工具参数不对。'


def run(
    *,
    base_url: str,
    model: str,
    api_key: str,
    user_message: str,
    project,
    tasks,
    library,
    on_step: Callable[[int, list[dict]], None] | None = None,
) -> tuple[str, list[dict]]:
    messages: list[dict] = [
        {'role': 'system', 'content': SYSTEM},
        {
            'role': 'user',
            'content': (
                f'{_context(project, tasks, library)}\n\n'
                f'用户：{user_message}\n\n'
                '先看目录和关键文件，再下结论。'
            ),
        },
    ]
    steps: list[dict] = []

    for index in range(1, MAX_STEPS + 1):
        data = ai_client.complete_json(
            base_url=base_url, model=model, api_key=api_key, messages=messages
        )
        tool = str(data.get('tool') or '').strip()
        args = data.get('args') if isinstance(data.get('args'), dict) else {}
        thought = str(data.get('thought') or '').strip()[:200]

        if tool == 'finish':
            answer = str(data.get('answer') or '').strip()
            if answer:
                return answer, steps
            break

        result = _run_tool(tool, args)
        result = result[: agent_tools.MAX_RESULT_CHARS]
        first_line = (result.splitlines() or [''])[0]
        steps.append(
            {
                'tool': tool,
                'args': {
                    key: str(value)[:200]
                    for key, value in args.items()
                    if key in {'path', 'query'}
                },
                'summary': first_line[:90],
            }
        )
        if on_step is not None:
            on_step(index, steps)

        messages.append(
            {
                'role': 'assistant',
                'content': json.dumps(
                    {'thought': thought, 'tool': tool, 'args': args},
                    ensure_ascii=False,
                )[:2000],
            }
        )
        messages.append(
            {'role': 'user', 'content': f'工具结果（第 {index} 步）：\n{result}'}
        )

    messages.append(
        {
            'role': 'user',
            'content': '停止调用工具，直接用中文给出计划。'
            '只输出 {"thought":"...","tool":"finish","answer":"..."}。',
        }
    )
    data = ai_client.complete_json(
        base_url=base_url, model=model, api_key=api_key, messages=messages
    )
    answer = str(data.get('answer') or data.get('thought') or '').strip()
    return answer or 'Agent 没有给出计划。', steps
