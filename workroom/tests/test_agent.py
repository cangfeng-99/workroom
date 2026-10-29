"""Tests for the read-only project agent (tools + loop + job)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from apps.projects import agent, agent_tools, crypto, views
from apps.projects.models import ChatMessage, Member, Project, ReplyJob


class AgentToolTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        base = Path(self.tmp)
        (base / 'app.py').write_text('def login():\n    pass\n', encoding='utf-8')
        (base / '.env').write_text('SECRET=1', encoding='utf-8')
        (base / 'sub').mkdir()
        (base / 'sub' / 'note.md').write_text('同步与冲突处理', encoding='utf-8')
        self.override = override_settings(AGENT_ROOT=self.tmp)
        self.override.enable()

    def tearDown(self) -> None:
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_and_read(self) -> None:
        listing = agent_tools.list_dir('.')
        self.assertIn('[file] app.py', listing)
        self.assertIn('[dir] sub', listing)
        self.assertNotIn('.env', listing)
        self.assertIn('def login', agent_tools.read_file('app.py'))

    def test_traversal_is_blocked(self) -> None:
        with self.assertRaises(agent_tools.ToolError):
            agent_tools.read_file('../outside.txt')

    def test_secret_is_blocked(self) -> None:
        with self.assertRaises(agent_tools.ToolError):
            agent_tools.read_file('.env')

    def test_search(self) -> None:
        self.assertIn('冲突', agent_tools.search('冲突'))


class AgentLoopTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        (Path(self.tmp) / 'README.md').write_text('项目说明', encoding='utf-8')
        self.override = override_settings(AGENT_ROOT=self.tmp)
        self.override.enable()
        self.project = Project.objects.create(name='P', goal_title='上线')

    def tearDown(self) -> None:
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_loop_runs_a_tool_then_finishes(self) -> None:
        replies = [
            {'thought': '先看目录', 'tool': 'list_dir', 'args': {'path': '.'}},
            {'thought': '够了', 'tool': 'finish', 'answer': '计划：先做同步'},
        ]
        with mock.patch(
            'apps.projects.agent.ai_client.complete_json', side_effect=replies
        ) as call:
            answer, steps = agent.run(
                base_url='https://api.deepseek.com',
                model='deepseek-v4-flash',
                api_key='sk-test',
                user_message='看下项目',
                project=self.project,
                tasks=[],
                library=[],
            )

        self.assertEqual(answer, '计划：先做同步')
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]['tool'], 'list_dir')
        self.assertIn('README.md', steps[0]['summary'])

    def test_agent_mode_starts_an_agent_job(self) -> None:
        ai = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='AI',
            provider='deepseek',
            model_name='deepseek-v4-flash',
            key_ciphertext=crypto.protect('sk-test'),
        )
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(
                f'/p/{self.project.pk}/chat/',
                {'message': '看下项目', 'mode': 'agent', 'ai': ai.pk},
            )
        self.assertEqual(start.call_args.args[3], ReplyJob.Mode.AGENT)

    def test_agent_job_writes_answer_and_steps(self) -> None:
        ai = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='AI',
            provider='deepseek',
            model_name='deepseek-v4-flash',
            key_ciphertext=crypto.protect('sk-test'),
        )
        job = ReplyJob.objects.create(
            project=self.project,
            member=ai,
            prompt='看下项目',
            mode=ReplyJob.Mode.AGENT,
        )
        with mock.patch(
            'apps.projects.views.agent.run',
            return_value=(
                '计划',
                [{'tool': 'list_dir', 'args': {'path': '.'}, 'summary': '[file] README.md'}],
            ),
        ):
            views._run_job(job.pk)

        message = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.assertEqual(message.content, '计划')
        self.assertEqual(message.agent_steps[0]['tool'], 'list_dir')

        html = self.client.get(
            f'/p/{self.project.pk}/?tab=chat'
        ).content.decode('utf-8')
        self.assertIn('执行步骤', html)
        self.assertIn('list_dir', html)
