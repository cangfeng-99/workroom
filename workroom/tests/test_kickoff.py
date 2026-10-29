"""S1: kickoff agenda, persona lens and dual-layer draft fields."""

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.projects import ai_client, crypto, planner
from apps.projects.models import ChatMessage, Member, Project, ProjectMembership, Task


class KickoffPromptTests(TestCase):
    def test_kickoff_agenda_mentions_personas(self) -> None:
        messages = ai_client.discussion_messages(
            phase='proposal',
            member={'name': 'GLM', 'role': '产品', 'persona': ''},
            user_message='【立项会】做一个面向小团队的项目管理工具',
            project_context='Agent开发',
            transcript='',
            kickoff=True,
        )
        system = messages[0]['content']
        self.assertIn('用户画像', system)
        self.assertIn('3 类用户', system)
        self.assertIn('边界', system)

    def test_normal_discussion_keeps_old_prompt(self) -> None:
        messages = ai_client.discussion_messages(
            phase='proposal',
            member={'name': 'GLM', 'role': '产品', 'persona': ''},
            user_message='随便聊聊',
            project_context='Agent开发',
            transcript='',
            kickoff=False,
        )
        self.assertNotIn('用户画像', messages[0]['content'])


class DualLayerDraftTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='S1', goal_title='上线')
        self.member = Member.objects.create(
            project=self.project, kind=Member.Kind.AI, name='GLM'
        )
        self.user = get_user_model().objects.create_user('editor', password='x')
        ProjectMembership.objects.create(
            project=self.project, user=self.user, role=ProjectMembership.Role.EDITOR
        )

    def test_validate_keeps_human_and_execution_fields(self) -> None:
        payload = {
            'tasks': [
                {
                    'ref': 'a',
                    'title': '任务',
                    'start_date': date.today().isoformat(),
                    'end_date': date.today().isoformat(),
                    'why': '因为没有它用户没法开始',
                    'outcome': '用户能一键开始',
                    'estimate': '0.5 人日',
                    'acceptance': '点一下就能进',
                    'guide': {'summary': '人话摘要', 'steps': ['第一步']},
                    'execution_spec': {
                        'work_kind': 'code',
                        'risk': 'high',
                        'allowed_paths': ['workroom/**'],
                        'check_commands': ['pytest -q'],
                    },
                }
            ]
        }
        tasks = planner.validate(payload, [self.member], date.today(), date.today())
        task = tasks[0]
        self.assertEqual(task['why'], '因为没有它用户没法开始')
        self.assertEqual(task['estimate'], '0.5 人日')
        self.assertEqual(task['guide']['summary'], '人话摘要')
        self.assertEqual(task['execution_spec']['risk'], 'high')

    def test_apply_persists_dual_layer(self) -> None:
        message = ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.ASSISTANT,
            content='草案',
            payload={
                'tasks': [
                    {
                        'ref': 'a',
                        'title': '任务',
                        'detail': '做点事',
                        'acceptance': '能点',
                        'why': '用户需要它',
                        'estimate': '0.5 人日',
                        'guide': {'summary': '人话', 'outcomes': ['能点']},
                        'execution_spec': {'risk': 'normal', 'allowed_paths': ['a/**']},
                    }
                ]
            },
        )
        self.client.force_login(self.user)
        with override_settings(WORKROOM_MODE='server'):
            self.client.post(f'/p/{self.project.pk}/drafts/{message.pk}/apply/')
        task = Task.objects.get(project=self.project, title='任务')
        self.assertEqual(task.guide.get('summary'), '人话')
        self.assertEqual(task.execution_spec.get('risk'), 'normal')
        self.assertEqual(task.acceptance, '能点')
        self.assertEqual(task.guide.get('why'), '用户需要它')
        self.assertEqual(task.guide.get('estimate'), '0.5 人日')

    def test_kickoff_mode_starts_discussion_with_marker(self) -> None:
        self.member.key_ciphertext = crypto.protect('sk-test')
        self.member.save(update_fields=['key_ciphertext'])
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.force_login(self.user)
            with override_settings(WORKROOM_MODE='server'):
                self.client.post(
                    f'/p/{self.project.pk}/chat/',
                    {'message': '做一个记账工具', 'mode': 'kickoff'},
                )
        self.assertTrue(start.called)
        args = start.call_args.args
        self.assertEqual(args[2].startswith('【立项会】'), True)
        self.assertEqual(args[3], 'discuss')
