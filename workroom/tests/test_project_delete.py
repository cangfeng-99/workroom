"""Tests for deleting a project and its cascade."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.projects import crypto
from apps.projects.models import (
    ChatMessage,
    LibraryEntry,
    Member,
    Project,
    ReplyJob,
    Task,
)


class ProjectDeleteTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='要删的项目', goal_title='上线')
        Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我'
        )
        Task.objects.create(project=self.project, title='任务')
        ChatMessage.objects.create(
            project=self.project, role=ChatMessage.Role.USER, content='你好'
        )
        LibraryEntry.objects.create(
            project=self.project, kind=LibraryEntry.Kind.RULE, title='规则'
        )
        ReplyJob.objects.create(project=self.project, prompt='x')

    def test_delete_removes_project_and_children(self) -> None:
        response = self.client.post(
            reverse('projects:delete', args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('projects:index'))
        self.assertFalse(Project.objects.filter(pk=self.project.pk).exists())
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(ChatMessage.objects.count(), 0)
        self.assertEqual(LibraryEntry.objects.count(), 0)
        self.assertEqual(ReplyJob.objects.count(), 0)
        self.assertEqual(Member.objects.count(), 0)

    def test_only_post_is_allowed(self) -> None:
        response = self.client.get(reverse('projects:delete', args=[self.project.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

    def test_rail_has_project_delete(self) -> None:
        html = self.client.get(
            reverse('projects:space', args=[self.project.pk])
        ).content.decode('utf-8')
        self.assertIn('rail-del-btn', html)
        self.assertIn('删除项目', html)

    def test_chat_toolbar_hidden_when_ai_exists(self) -> None:
        Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='AI',
            provider='deepseek',
            model_name='deepseek-v4-flash',
            key_ciphertext=crypto.protect('sk-test'),
        )
        html = self.client.get(
            reverse('projects:space', args=[self.project.pk]) + '?tab=chat'
        ).content.decode('utf-8')
        self.assertNotIn('还没有能对话的 AI', html)

    def test_chat_toolbar_warns_without_ai(self) -> None:
        html = self.client.get(
            reverse('projects:space', args=[self.project.pk]) + '?tab=chat'
        ).content.decode('utf-8')
        self.assertIn('还没有能对话的 AI', html)

    def test_index_has_delete_control(self) -> None:
        html = self.client.get(reverse('projects:index')).content.decode('utf-8')
        self.assertIn('card-del-btn', html)
        self.assertIn('删除项目', html)
