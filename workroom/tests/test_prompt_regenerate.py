"""Prompt draft card: keep the original wording, ask for another version."""

from unittest.mock import patch

from django.test import TestCase

from apps.projects import crypto, views
from apps.projects.models import ChatMessage, Member, Project, ReplyJob

FAKE_DRAFT = {
    'role': '项目助理',
    'task': '把登录页按钮改成绿色',
    'context': '内部系统',
    'goal': '减少误点',
    'constraints': '不动接口',
    'output': '改完的代码',
    'acceptance': '按钮为绿色且可点击',
}


class PromptRegenerateTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='目标')
        self.member = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='GLM',
            provider='zhipu',
            model_name='glm-4.6',
            key_ciphertext=crypto.protect('sk-test'),
        )

    def _draft(self, original: str = '把登录页改成绿色', **extra) -> ChatMessage:
        payload = {'source': 'prompt-draft', 'prompt_draft': dict(FAKE_DRAFT)}
        if original:
            payload['prompt_original'] = original
        payload.update(extra)
        return ChatMessage.objects.create(
            project=self.project,
            member=self.member,
            role=ChatMessage.Role.ASSISTANT,
            content='我理解的需求如下',
            payload=payload,
        )

    def test_regenerate_keeps_original_wording(self) -> None:
        message = self._draft()
        with patch.object(views, '_start_job') as start:
            response = self.client.post(
                f'/p/{self.project.pk}/prompts/{message.pk}/regenerate/'
            )
        self.assertEqual(response.status_code, 302)
        start.assert_called_once()
        args = start.call_args.args
        self.assertEqual(args[0], self.project)
        self.assertEqual(args[1], self.member)
        self.assertEqual(args[2], '【提示词】把登录页改成绿色')

    def test_regenerate_falls_back_to_user_message(self) -> None:
        ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.USER,
            content='【提示词】从聊天记录里取原话',
        )
        message = self._draft(original='')
        with patch.object(views, '_start_job') as start:
            self.client.post(f'/p/{self.project.pk}/prompts/{message.pk}/regenerate/')
        start.assert_called_once()
        self.assertEqual(start.call_args.args[2], '【提示词】从聊天记录里取原话')

    def test_non_draft_message_is_ignored(self) -> None:
        message = ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.ASSISTANT,
            content='普通回复',
            payload={'source': 'chat'},
        )
        with patch.object(views, '_start_job') as start:
            response = self.client.post(
                f'/p/{self.project.pk}/prompts/{message.pk}/regenerate/'
            )
        self.assertEqual(response.status_code, 302)
        start.assert_not_called()

    def test_second_draft_bumps_version_and_supersedes_first(self) -> None:
        job = ReplyJob.objects.create(
            project=self.project,
            member=self.member,
            mode=ReplyJob.Mode.CHAT,
            prompt='【提示词】把登录页改成绿色',
        )
        with patch.object(views.ai_client, 'complete_json', return_value=FAKE_DRAFT):
            views._run_prompt_draft(job)
            views._run_prompt_draft(job)
        drafts = [
            message
            for message in ChatMessage.objects.filter(project=self.project).order_by('pk')
            if (message.payload or {}).get('source') == 'prompt-draft'
        ]
        self.assertEqual(len(drafts), 2)
        first, second = drafts
        self.assertEqual(first.payload['prompt_version'], 1)
        self.assertEqual(second.payload['prompt_version'], 2)
        self.assertTrue(first.payload.get('prompt_superseded'))
        self.assertFalse(second.payload.get('prompt_superseded'))
        self.assertEqual(second.payload['prompt_original'], '把登录页改成绿色')
        self.assertEqual(second.payload['regenerate_from'], first.pk)

    def test_superseded_card_keeps_apply_hidden(self) -> None:
        message = self._draft(prompt_version=1)
        views._supersede_draft(message)
        message.refresh_from_db()
        self.assertTrue(message.payload['prompt_superseded'])
