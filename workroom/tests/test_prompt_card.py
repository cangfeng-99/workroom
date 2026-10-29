"""Prompt confirmation card: draft, edit, confirm and run."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.projects import crypto
from apps.projects.models import ChatMessage, Member, Project, ProjectMembership, ReplyJob
from apps.projects import views


class PromptCardTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='Prompt', goal_title='上线')
        self.member = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='GLM',
            key_ciphertext=crypto.protect('sk-test'),
        )
        self.user = get_user_model().objects.create_user('owner', password='x')
        ProjectMembership.objects.create(
            project=self.project, user=self.user, role=ProjectMembership.Role.OWNER
        )
        self.client.force_login(self.user)

    def test_draft_creates_message_with_seven_fields(self) -> None:
        job = ReplyJob.objects.create(
            project=self.project,
            member=self.member,
            prompt='【提示词】做个登录页',
            mode=ReplyJob.Mode.CHAT,
        )
        payload = {
            'role': '资深前端工程师',
            'task': '实现登录页',
            'context': '已有 Django 后端',
            'goal': '可用',
            'constraints': '不改后端',
            'output': '代码',
            'acceptance': '能登录',
        }
        with mock.patch(
            'apps.projects.ai_client.complete_json', return_value=payload
        ):
            views._run_prompt_draft(job)
        message = ChatMessage.objects.get(project=self.project)
        draft = message.payload['prompt_draft']
        self.assertEqual(draft['role'], '资深前端工程师')
        self.assertEqual(len(draft), 7)

    def test_apply_composes_and_starts_job(self) -> None:
        message = ChatMessage.objects.create(
            project=self.project,
            member=self.member,
            role=ChatMessage.Role.ASSISTANT,
            content='请确认',
            payload={
                'prompt_draft': {
                    'role': '产品经理',
                    'task': '拆需求',
                    'context': '',
                    'goal': '',
                    'constraints': '',
                    'output': '',
                    'acceptance': '',
                }
            },
        )
        with mock.patch('apps.projects.views._start_job') as start:
            with override_settings(WORKROOM_MODE='server'):
                response = self.client.post(
                    f'/p/{self.project.pk}/prompts/{message.pk}/apply/',
                    {'role': '产品经理', 'task': '拆需求'},
                )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(start.called)
        prompt = start.call_args.args[2]
        self.assertIn('你是产品经理', prompt)
        self.assertIn('任务：拆需求', prompt)
        message.refresh_from_db()
        self.assertTrue(message.payload.get('prompt_applied'))

    def test_prompt_mode_starts_marked_job(self) -> None:
        with mock.patch('apps.projects.views._start_job') as start:
            with override_settings(WORKROOM_MODE='server'):
                self.client.post(
                    f'/p/{self.project.pk}/chat/',
                    {'message': '做个登录页', 'mode': 'prompt'},
                )
        self.assertTrue(start.called)
        self.assertTrue(start.call_args.args[2].startswith('【提示词】'))
