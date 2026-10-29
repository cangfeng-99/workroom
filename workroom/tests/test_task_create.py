"""Manual task creation from the task tree."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.projects.models import Member, Project, ProjectMembership, Task


class TaskCreateTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='Create', goal_title='上线')
        self.member = Member.objects.create(
            project=self.project, kind=Member.Kind.AI, name='GLM'
        )
        self.owner = get_user_model().objects.create_user('owner', password='x')
        ProjectMembership.objects.create(
            project=self.project, user=self.owner, role=ProjectMembership.Role.OWNER
        )
        self.editor = get_user_model().objects.create_user('editor', password='x')
        ProjectMembership.objects.create(
            project=self.project, user=self.editor, role=ProjectMembership.Role.EDITOR
        )
        self.url = f'/p/{self.project.pk}/tasks/create/'

    def test_owner_creates_with_parent_assignee_and_dates(self) -> None:
        parent = Task.objects.create(project=self.project, title='父任务')
        self.client.force_login(self.owner)
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.post(
                self.url,
                {
                    'title': '新任务',
                    'detail': '做点事',
                    'parent': parent.pk,
                    'assignee': self.member.pk,
                    'start_date': '2026-10-27',
                    'end_date': '2026-10-30',
                },
            )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(project=self.project, title='新任务')
        self.assertEqual(task.parent, parent)
        self.assertEqual(task.assignee, self.member)
        self.assertEqual(task.start_date, date(2026, 10, 27))

    def test_editor_cannot_assign_owner_only(self) -> None:
        self.client.force_login(self.editor)
        with override_settings(WORKROOM_MODE='server'):
            self.client.post(
                self.url, {'title': '编辑者的任务', 'assignee': self.member.pk}
            )
        task = Task.objects.get(project=self.project, title='编辑者的任务')
        self.assertIsNone(task.assignee)

    def test_foreign_parent_is_ignored(self) -> None:
        other = Project.objects.create(name='Other', goal_title='别的')
        foreign = Task.objects.create(project=other, title='外项目任务')
        self.client.force_login(self.owner)
        with override_settings(WORKROOM_MODE='server'):
            self.client.post(self.url, {'title': '我的任务', 'parent': foreign.pk})
        task = Task.objects.get(project=self.project, title='我的任务')
        self.assertIsNone(task.parent)

    def test_non_member_is_rejected(self) -> None:
        outsider = get_user_model().objects.create_user('outsider', password='x')
        self.client.force_login(outsider)
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.post(self.url, {'title': '不应创建'})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Task.objects.filter(title='不应创建').exists())

    def test_empty_title_is_rejected(self) -> None:
        self.client.force_login(self.owner)
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.post(self.url, {'title': '   '})
        self.assertEqual(response.status_code, 400)
