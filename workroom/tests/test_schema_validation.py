"""Argument validation: a failed call must say which field is wrong.

The point of these tests is the message, not the boolean. A model that is told
"参数不符合schema" can only guess; one that is told which field and how to fix it
can recover on the next try.
"""

import tempfile

from django.test import TestCase

from apps.projects import directives, mcp, schema_check
from apps.projects.models import Project, Task
from tool_schema import TOOLS


def _schema(name: str) -> dict:
    return next(tool['inputSchema'] for tool in TOOLS if tool['name'] == name)


class CheckerTests(TestCase):
    def test_missing_required_names_the_field(self) -> None:
        _, errors, _ = schema_check.check({'project': 'p'}, _schema('create_task'))
        self.assertTrue(any('title' in item for item in errors))

    def test_project_is_not_hard_required(self) -> None:
        """令牌已绑定项目时调用方可以省略 project，schema 不该拦。"""
        clean, errors, _ = schema_check.check(
            {'task': '1', 'summary': 's'}, _schema('submit_result')
        )
        self.assertEqual(errors, [])
        self.assertNotIn('project', clean)

    def test_wrong_type_reports_expected_and_actual(self) -> None:
        _, errors, _ = schema_check.check(
            {'project': 'p', 'title': 'x', 'start_date': 20261105},
            _schema('create_task'),
        )
        message = ' '.join(errors)
        self.assertIn('start_date', message)
        self.assertIn('文本', message)
        self.assertIn('integer', message)

    def test_unknown_field_is_dropped_not_fatal(self) -> None:
        clean, errors, warnings = schema_check.check(
            {'project': 'p', 'title': 'x', 'status': 'done'},
            _schema('create_task'),
        )
        self.assertEqual(errors, [])
        self.assertNotIn('status', clean)
        self.assertTrue(any('status' in item for item in warnings))

    def test_numeric_string_is_coerced(self) -> None:
        clean, errors, warnings = schema_check.check(
            {'project': 'p', 'task': '1', 'summary': 's', 'test_exit_code': '0'},
            _schema('submit_result'),
        )
        self.assertEqual(errors, [])
        self.assertEqual(clean['test_exit_code'], 0)
        self.assertTrue(warnings)

    def test_string_false_is_not_truthy(self) -> None:
        """``bool('false')`` is True; the coercion must not fall into that."""
        clean, _, _ = schema_check.check(
            {'project': 'p', 'task': '1', 'summary': 's', 'review': 'false'},
            _schema('submit_result'),
        )
        self.assertIs(clean['review'], False)

    def test_enum_violation_is_reported(self) -> None:
        _, errors, _ = schema_check.check(
            {'project': 'p', 'title': 'x', 'kind': 'diagram'},
            _schema('add_library_entry'),
        )
        self.assertTrue(any('kind' in item and 'rule' in item for item in errors))

    def test_enum_does_not_leak_between_fields(self) -> None:
        """同类型字段共用同一个 dict 实例，加 enum 时复制才不会传染。"""
        schema = _schema('submit_result')
        self.assertNotIn('enum', schema['properties']['evidence_ref'])
        self.assertNotIn('enum', schema['properties']['idempotency_key'])
        self.assertEqual(
            _schema('review_delivery')['properties']['verdict']['enum'],
            ['approved', 'changes'],
        )

    def test_explain_lists_fields_and_example(self) -> None:
        schema = _schema('create_task')
        _, errors, warnings = schema_check.check({'title': 'x'}, schema)
        text = schema_check.explain('create_task', errors, warnings, schema)
        self.assertIn('create_task', text)
        self.assertIn('可用字段', text)
        self.assertIn('最小可用调用', text)

    def test_non_object_arguments_are_rejected(self) -> None:
        clean, errors, _ = schema_check.check(['project'], _schema('create_task'))
        self.assertEqual(clean, {})
        self.assertTrue(errors)


class CallToolTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Project.objects.create(
            name='A', goal_title='G', workspace_path=self.tmp.name
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bad_call_raises_readable_error(self) -> None:
        with self.assertRaises(mcp.McpError) as caught:
            mcp.call_tool('create_task', {'project': 'p', 'title': 123})
        message = caught.exception.message
        self.assertIn('create_task', message)
        self.assertIn('title', message)

    def test_missing_project_in_local_mode_still_explains(self) -> None:
        """本地模式没有令牌兜底，缺 project 要给出可读提示。"""
        with self.assertRaises(mcp.McpError) as caught:
            mcp.call_tool('create_task', {'title': '没有项目'})
        self.assertIn('project', caught.exception.message)

    def test_extra_field_does_not_block_the_call(self) -> None:
        text = mcp.call_tool(
            'create_task',
            {'project': str(self.project.pk), 'title': '校验过的任务', 'status': 'done'},
        )
        self.assertIn('已创建任务', text)
        self.assertIn('status', text)  # 提示被忽略，而不是静默丢弃
        self.assertTrue(Task.objects.filter(title='校验过的任务').exists())

    def test_unknown_tool_still_reported(self) -> None:
        with self.assertRaises(mcp.McpError):
            mcp.call_tool('no_such_tool', {})


class DirectiveValidationTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Project.objects.create(
            name='A', goal_title='G', workspace_path=self.tmp.name
        )
        self.root = Task.objects.create(
            project=self.project, title='10 全生命周期地图', status=Task.Status.DOING
        )
        for title in ('00 立项前期', '10 方案设计', '20 开发实现',
                      '30 测试验收', '40 发布试用', '50 复盘迭代'):
            Task.objects.create(project=self.project, parent=self.root, title=title)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_directive_date_is_written(self) -> None:
        _, actions = directives.apply_with_log(
            self.project, '[[task:写迁移脚本| |2026-11-05|补数据]]'
        )
        task = Task.objects.get(title='写迁移脚本')
        self.assertEqual(task.start_date.isoformat(), '2026-11-05')
        self.assertEqual(task.end_date.isoformat(), '2026-11-12')
        self.assertEqual([item['kind'] for item in actions], ['task'])

    def test_bad_date_is_reported_not_guessed(self) -> None:
        _, actions = directives.apply_with_log(
            self.project, '[[task:写迁移脚本||2026-13-45|补数据]]'
        )
        task = Task.objects.get(title='写迁移脚本')
        self.assertIsNone(task.start_date)
        warn = next(item for item in actions if item['kind'] == 'warn')
        self.assertIn('2026-13-45', warn['label'])

    def test_unknown_owner_is_reported(self) -> None:
        _, actions = directives.apply_with_log(
            self.project, '[[task:写迁移脚本|查无此人|2026-11-05|补数据]]'
        )
        task = Task.objects.get(title='写迁移脚本')
        self.assertIsNone(task.assignee)
        warn = next(item for item in actions if item['kind'] == 'warn')
        self.assertIn('查无此人', warn['label'])

    def test_overflow_is_reported(self) -> None:
        text = ' '.join(f'[[task:任务{i}|||说明]]' for i in range(5))
        _, actions = directives.apply_with_log(self.project, text)
        created = [item for item in actions if item['kind'] == 'task']
        self.assertEqual(len(created), 3)
        warn = next(item for item in actions if item['kind'] == 'warn')
        self.assertIn('2', warn['label'])
