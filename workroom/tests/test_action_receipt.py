"""Directive execution leaves a receipt the user can verify."""

import tempfile

from django.test import TestCase

from apps.projects import directives
from apps.projects.models import Project, Task


class ActionReceiptTests(TestCase):
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

    def test_created_task_is_reported(self) -> None:
        text, actions = directives.apply_with_log(
            self.project, '好了 [[task:写使用说明|GLM||补文档]]'
        )
        self.assertNotIn('[[task', text)
        kinds = [item['kind'] for item in actions]
        self.assertIn('task', kinds)
        created = next(item for item in actions if item['kind'] == 'task')
        self.assertTrue(created['label'].startswith('40'))
        self.assertTrue(Task.objects.filter(pk=created['id']).exists())

    def test_duplicate_is_skipped_with_reason(self) -> None:
        Task.objects.create(project=self.project, title='写使用说明')
        _, actions = directives.apply_with_log(
            self.project, '[[task:写使用说明|GLM||补文档]]'
        )
        self.assertEqual(actions[0]['kind'], 'skip')

    def test_done_claim_is_blocked(self) -> None:
        task = Task.objects.create(
            project=self.project, title='打包', status=Task.Status.DOING
        )
        text, actions = directives.apply_with_log(
            self.project, '[[status:打包|done]]'
        )
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DOING)
        self.assertEqual(actions[0]['kind'], 'blocked')
        self.assertIn('交付', text)

    def test_status_change_is_reported(self) -> None:
        task = Task.objects.create(
            project=self.project, title='打包', status=Task.Status.TODO
        )
        _, actions = directives.apply_with_log(
            self.project, '[[status:打包|doing]]'
        )
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DOING)
        self.assertEqual(actions[0]['kind'], 'status')

    def test_memory_is_reported(self) -> None:
        _, actions = directives.apply_with_log(
            self.project, '记一下 [[memory-long:单人版优先]]'
        )
        self.assertEqual(actions[0]['kind'], 'memory')
        self.assertEqual(actions[0]['label'], '长期记忆')
