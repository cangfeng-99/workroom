"""Project page must not degrade into N+1 queries."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.projects.models import ChatMessage, Delivery, Member, Project, Task

BUDGET = 30


class QueryBudgetTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='Q', goal_title='G')
        owner = Member.objects.create(project=self.project, name='我')
        root = Task.objects.create(
            project=self.project, title='10 全生命周期地图', status=Task.Status.DOING
        )
        for index, stage_title in enumerate(
            ('00 立项前期', '10 方案设计', '20 开发实现', '30 测试验收', '40 发布试用')
        ):
            stage = Task.objects.create(
                project=self.project, parent=root, title=stage_title,
                status=Task.Status.DOING, assignee=owner,
            )
            for n in range(4):
                task = Task.objects.create(
                    project=self.project, parent=stage,
                    title=f'{stage_title}-{n}', assignee=owner,
                    status=Task.Status.DONE if n % 2 else Task.Status.TODO,
                )
                Delivery.objects.create(
                    task=task, summary='x', status='pending', idempotency_key=f'{task.pk}-{n}'
                )
        for n in range(12):
            ChatMessage.objects.create(
                project=self.project, member=owner,
                role=ChatMessage.Role.ASSISTANT, content=f'消息 {n}',
            )

    def _count(self, url: str) -> int:
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_tasks_tab_stays_within_budget(self) -> None:
        count = self._count(reverse('projects:space', args=[self.project.pk]))
        self.assertLessEqual(count, BUDGET, f'tasks 页查询 {count} 次，超过预算 {BUDGET}')

    def test_chat_tab_stays_within_budget(self) -> None:
        url = reverse('projects:space', args=[self.project.pk]) + '?tab=chat'
        count = self._count(url)
        self.assertLessEqual(count, BUDGET, f'chat 页查询 {count} 次，超过预算 {BUDGET}')
