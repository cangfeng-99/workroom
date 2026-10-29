"""Capability-based task assignment."""

from django.test import TestCase

from apps.projects import assignment, crypto
from apps.projects.models import Member, Project, Task


class AssignmentTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='Assign', goal_title='上线')
        self.backend = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='赵擎',
            role='后端工程师',
            persona='Django / 接口 / 数据库',
            key_ciphertext=crypto.protect('sk-test'),
        )
        self.frontend = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='林屿',
            role='前端工程师',
            persona='ArkTS / 页面 / 组件',
            key_ciphertext=crypto.protect('sk-test'),
        )

    def test_infer_kind(self) -> None:
        self.assertEqual(assignment.infer_kind('实现登录接口和鉴权'), 'backend')
        self.assertEqual(assignment.infer_kind('调整登录页布局'), 'frontend')
        self.assertEqual(assignment.infer_kind('补充回归用例'), 'test')

    def test_fill_matches_roles_and_keeps_explicit(self) -> None:
        tasks = [
            {'title': '实现登录接口', 'detail': '数据库与鉴权', 'assignee_id': None},
            {'title': '登录页组件', 'detail': '样式与交互', 'assignee_id': self.frontend.pk},
        ]
        assignment.fill(tasks, self.project)
        self.assertEqual(tasks[0]['assignee_id'], self.backend.pk)
        self.assertEqual(tasks[1]['assignee_id'], self.frontend.pk)

    def test_no_match_leaves_empty(self) -> None:
        self.backend.delete()
        self.frontend.delete()
        member = assignment.pick(self.project, 'backend')
        self.assertIsNone(member)
        tasks = [{'title': '部署上线', 'detail': '服务器', 'assignee_id': None}]
        assignment.fill(tasks, self.project)
        self.assertIsNone(tasks[0]['assignee_id'])
