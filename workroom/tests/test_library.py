"""Tests for the P0-P2 library features."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.projects import library
from apps.projects.models import ChatMessage, LibraryEntry, Member, Project, Task


class LibraryFeatureTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        self.member = Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我'
        )
        self.task = Task.objects.create(project=self.project, title='登录模块')
        self.entry = LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.RULE,
            title='只做 P0',
            body='这版只保证登录和看板能用',
            summary='范围锁死',
            tags='范围,登录',
        )

    def test_prompt_block_includes_summary_and_body(self) -> None:
        block = library.prompt_block(self.project)
        self.assertIn('只做 P0', block)
        self.assertIn('范围锁死', block)
        self.assertIn('规则约束', block)

        LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.RULE,
            title='离线优先',
            body='断网也能编辑',
        )
        block = library.prompt_block(self.project)
        self.assertIn('断网也能编辑', block)

    def test_capture_from_message(self) -> None:
        message = ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.ASSISTANT,
            content='## 结论\n先做登录，其他进二期。',
        )
        response = self.client.post(
            reverse('projects:library_capture', args=[self.project.pk, message.pk]),
            {'kind': 'decision', 'title': '先做登录'},
        )
        self.assertEqual(response.status_code, 302)
        entry = self.project.library.get(title='先做登录')
        self.assertEqual(entry.source, LibraryEntry.Source.AI)
        self.assertEqual(entry.source_ref, f'chat:{message.pk}')
        self.assertIn('先做登录，其他进二期', entry.body)

    def test_edit_updates_structured_fields_and_task(self) -> None:
        response = self.client.post(
            reverse('projects:library_edit', args=[self.project.pk, self.entry.pk]),
            {
                'kind': 'decision',
                'title': '只做 P0',
                'summary': '一期只做登录',
                'body': '正文',
                'context': '时间不够',
                'options': 'A: 全做；B: 只做 P0',
                'conclusion': '选 B',
                'tags': '范围,一期',
                'task': self.task.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.kind, LibraryEntry.Kind.DECISION)
        self.assertEqual(self.entry.context, '时间不够')
        self.assertEqual(self.entry.conclusion, '选 B')
        self.assertEqual(self.entry.task, self.task)
        self.assertEqual(self.entry.tag_list, ['范围', '一期'])

    def test_search_matches_body(self) -> None:
        url = reverse('projects:space', args=[self.project.pk])
        html = self.client.get(f'{url}?tab=library&q=看板').content.decode('utf-8')
        self.assertIn('只做 P0', html)
        html = self.client.get(f'{url}?tab=library&q=不存在的词').content.decode('utf-8')
        self.assertNotIn('只做 P0', html)

    def test_add_links_task(self) -> None:
        self.client.post(
            reverse('projects:library_add', args=[self.project.pk]),
            {
                'kind': 'artifact',
                'title': '登录接口约定',
                'body': 'POST /login',
                'task': self.task.pk,
            },
        )
        entry = self.project.library.get(title='登录接口约定')
        self.assertEqual(entry.task, self.task)
