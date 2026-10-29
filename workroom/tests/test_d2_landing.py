"""D2: task landing loop invariants (apply idempotency, scope, status rules)."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.projects.models import ChatMessage, Member, Project, ProjectMembership, Task


class DraftApplyTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='D2', goal_title='上线')
        self.member = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='GLM',
            role='实现',
        )
        self.user = get_user_model().objects.create_user('editor', password='x')
        ProjectMembership.objects.create(
            project=self.project,
            user=self.user,
            role=ProjectMembership.Role.EDITOR,
        )
        self.message = ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.ASSISTANT,
            content='草案',
            payload={
                'tasks': [
                    {'ref': 'a', 'title': '根任务', 'assignee_id': self.member.pk},
                    {'ref': 'b', 'title': '子任务', 'parent_ref': 'a'},
                ]
            },
        )
        self.url = f'/p/{self.project.pk}/drafts/{self.message.pk}/apply/'

    def test_apply_creates_tree_and_is_idempotent(self) -> None:
        self.client.force_login(self.user)
        with override_settings(WORKROOM_MODE='server'):
            self.client.post(self.url)
            first = Task.objects.filter(project=self.project).count()
            self.client.post(self.url)
            second = Task.objects.filter(project=self.project).count()
        self.assertEqual(first, 2)
        self.assertEqual(second, 2)
        self.message.refresh_from_db()
        self.assertIsNotNone(self.message.applied_at)
        child = Task.objects.get(project=self.project, title='子任务')
        self.assertEqual(child.parent.title, '根任务')

    def test_foreign_assignee_is_ignored(self) -> None:
        other = Project.objects.create(name='Other', goal_title='别的')
        foreign = Member.objects.create(
            project=other, kind=Member.Kind.AI, name='外项目成员'
        )
        self.message.payload = {
            'tasks': [{'ref': 'a', 'title': '根', 'assignee_id': foreign.pk}]
        }
        self.message.save(update_fields=['payload'])
        self.client.force_login(self.user)
        with override_settings(WORKROOM_MODE='server'):
            self.client.post(self.url)
        task = Task.objects.get(project=self.project, title='根')
        self.assertIsNone(task.assignee)

    def test_non_member_cannot_apply(self) -> None:
        outsider = get_user_model().objects.create_user('outsider', password='x')
        self.client.force_login(outsider)
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Task.objects.filter(project=self.project).count(), 0)


class TaskStatusTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='D2s', goal_title='上线')
        self.user = get_user_model().objects.create_user('owner', password='x')
        ProjectMembership.objects.create(
            project=self.project,
            user=self.user,
            role=ProjectMembership.Role.OWNER,
        )
        self.task = Task.objects.create(project=self.project, title='任务')
        self.url = f'/p/{self.project.pk}/tasks/{self.task.pk}/status/'

    def test_done_is_rejected_in_server_mode(self) -> None:
        self.client.force_login(self.user)
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.post(self.url, {'status': 'done'})
        self.assertEqual(response.status_code, 403)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, Task.Status.DONE)

    def test_blocked_requires_reason(self) -> None:
        self.client.force_login(self.user)
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.post(self.url, {'status': 'blocked'})
        self.assertEqual(response.status_code, 400)
