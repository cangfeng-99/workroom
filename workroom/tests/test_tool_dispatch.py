"""Every advertised tool must at least be dispatchable.

A rename left ``ask_project_knowledge`` reading a variable that no longer
existed. 538 tests passed, because nothing ever called that tool: the breakage
lived in a code path no test walked through.

This walks the published tool list instead of a hand-written subset, so a tool
cannot hide behind being unused. Business rejections (``McpError`` and friends)
are expected — the contract only requires that the dispatcher itself is sound.
"""

import tempfile

from django.test import TestCase

from apps.projects import mcp
from apps.projects.delivery import DeliveryError
from apps.projects.models import Member, Project, Task
from tool_schema import TOOLS

# 名字/属性/局部变量写错，属于分发层坏了，而不是调用条件不满足。
PROGRAMMING_ERRORS = (NameError, AttributeError, UnboundLocalError, TypeError)

# 会真的等满 shortest timeout 的工具，单独测，避免拖慢整轮。
SLOW_TOOLS = {'wait_for_work'}

_TYPE_DEFAULTS = {
    'string': 'smoke',
    'integer': 1,
    'number': 1,
    'boolean': False,
    'object': {},
    'array': [],
}


class ToolDispatchTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Project.objects.create(
            name='Smoke', goal_title='G', workspace_path=self.tmp.name
        )
        self.member = Member.objects.create(
            project=self.project, name='Codex', kind=Member.Kind.EXTERNAL
        )
        self.task = Task.objects.create(
            project=self.project, title='work', assignee=self.member
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _arguments(self, schema: dict) -> dict:
        """Minimal plausible arguments: required fields plus project."""
        props = schema.get('properties', {})
        keys = list(schema.get('required') or [])
        if 'project' in props:
            keys.append('project')
        fixed = {
            'project': str(self.project.pk),
            'task': str(self.task.pk),
            'entry': str(self.task.pk),
            'delivery': str(self.task.pk),
            'assignee': 'Codex',
            'member': 'Codex',
            'title': 'smoke',
            'text': 'smoke',
            'label': 'smoke',
        }
        args: dict = {}
        for key in keys:
            if key in args:
                continue
            if key in fixed:
                args[key] = fixed[key]
                continue
            spec = props.get(key, {})
            kind = spec.get('type')
            if isinstance(kind, list):
                kind = next((item for item in kind if item), 'string')
            if 'enum' in spec and spec['enum']:
                args[key] = spec['enum'][0]
                continue
            args[key] = _TYPE_DEFAULTS.get(kind, 'smoke')
        return args

    def test_every_tool_dispatches_without_programming_error(self) -> None:
        for tool in TOOLS:
            name = tool['name']
            if name in SLOW_TOOLS:
                continue
            args = self._arguments(tool['inputSchema'])
            with self.subTest(tool=name):
                try:
                    mcp.call_tool(name, args)
                except (mcp.McpError, DeliveryError, PermissionError):
                    pass  # 业务前提不满足，不是分发层的问题
                except PROGRAMMING_ERRORS as exc:
                    self.fail(f'{name} 抛编程错误：{exc!r}')

    def test_wait_for_work_returns_on_timeout(self) -> None:
        text = mcp.call_tool(
            'wait_for_work',
            {'project': str(self.project.pk), 'assignee': 'Codex', 'timeout': 5},
        )
        self.assertIn('超时', text)
