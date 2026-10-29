"""Tests for external-tool team members (WorkBuddy / Codex / Cursor)."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects.models import Member, Project, Task


class ExternalMemberTests(TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / '.workbuddy').mkdir()
        (self.tmp / '.workbuddy' / 'mcp.json').write_text(
            json.dumps({'mcpServers': {'workroom': {}}}), encoding='utf-8'
        )
        self.override = override_settings(MCP_HOME=self.tmp)
        self.override.enable()
        self.project = Project.objects.create(name='P', goal_title='上线')
        Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我', role='负责人'
        )

    def tearDown(self) -> None:
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_join_creates_external_member_once(self) -> None:
        url = reverse(
            'projects:member_join_external', args=[self.project.pk, 'workbuddy']
        )
        self.client.post(url)
        self.client.post(url)
        members = self.project.members.filter(kind=Member.Kind.EXTERNAL)
        self.assertEqual(members.count(), 1)
        self.assertEqual(members.first().tool, 'workbuddy')
        self.assertEqual(members.first().name, 'WorkBuddy')

    def test_unconfigured_client_is_ignored(self) -> None:
        self.client.post(
            reverse('projects:member_join_external', args=[self.project.pk, 'cursor'])
        )
        self.assertFalse(
            self.project.members.filter(kind=Member.Kind.EXTERNAL).exists()
        )

    def test_external_settings_page_saves_identity(self) -> None:
        member = Member.objects.create(
            project=self.project,
            kind=Member.Kind.EXTERNAL,
            tool='workbuddy',
            name='WorkBuddy',
            role='执行',
        )
        url = reverse('projects:member_settings', args=[self.project.pk, member.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {'name': 'WB', 'role': '主力开发', 'persona': '改代码'})
        member.refresh_from_db()
        self.assertEqual(member.name, 'WB')
        self.assertEqual(member.role, '主力开发')

    def test_external_member_is_not_a_chat_responder(self) -> None:
        Member.objects.create(
            project=self.project,
            kind=Member.Kind.EXTERNAL,
            tool='workbuddy',
            name='WorkBuddy',
        )
        html = self.client.get(
            reverse('projects:space', args=[self.project.pk]) + '?tab=chat'
        ).content.decode('utf-8')
        self.assertNotIn('class="ai-select"', html)
        self.assertIn('WorkBuddy', html)

    def test_external_member_can_be_removed(self) -> None:
        member = Member.objects.create(
            project=self.project,
            kind=Member.Kind.EXTERNAL,
            tool='workbuddy',
            name='WorkBuddy',
        )
        self.client.post(
            reverse('projects:member_delete', args=[self.project.pk, member.pk])
        )
        member.refresh_from_db()
        self.assertFalse(member.is_active)


class TaskAssignTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        self.human = Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我'
        )
        self.external = Member.objects.create(
            project=self.project,
            kind=Member.Kind.EXTERNAL,
            tool='workbuddy',
            name='WorkBuddy',
            role='执行',
        )
        self.task = Task.objects.create(project=self.project, title='改登录页')

    def test_assign_to_external_member(self) -> None:
        response = self.client.post(
            reverse('projects:task_assign', args=[self.project.pk, self.task.pk]),
            {'assignee': self.external.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.external)

    def test_unassign(self) -> None:
        self.task.assignee = self.external
        self.task.save()
        self.client.post(
            reverse('projects:task_assign', args=[self.project.pk, self.task.pk]),
            {'assignee': ''},
        )
        self.task.refresh_from_db()
        self.assertIsNone(self.task.assignee)

    def test_member_from_another_project_is_rejected(self) -> None:
        other = Project.objects.create(name='Other', goal_title='x')
        stranger = Member.objects.create(
            project=other, kind=Member.Kind.HUMAN, name='别人'
        )
        self.client.post(
            reverse('projects:task_assign', args=[self.project.pk, self.task.pk]),
            {'assignee': stranger.pk},
        )
        self.task.refresh_from_db()
        self.assertIsNone(self.task.assignee)

    def test_inspector_has_assign_form(self) -> None:
        html = self.client.get(
            reverse('projects:space', args=[self.project.pk])
            + f'?tab=tasks&task={self.task.pk}'
        ).content.decode('utf-8')
        self.assertIn('改负责人', html)
        self.assertIn('WorkBuddy（外部）', html)
