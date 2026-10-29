"""Tests for the MCP bridge and the connect page."""

from __future__ import annotations

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects import crypto, mcp
from apps.projects.models import (
    ChatMessage,
    LibraryEntry,
    Member,
    Project,
    ReplyJob,
    Task,
)


class McpToolTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='演示项目', goal_title='上线')
        self.member = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='DeepSeek',
            role='后端',
        )
        self.task = Task.objects.create(
            project=self.project, title='登录模块', assignee=self.member
        )

    def test_list_and_get(self) -> None:
        self.assertIn('演示项目', mcp.list_projects())
        detail = mcp.get_project('演示项目')
        self.assertIn('登录模块', detail)
        self.assertIn('DeepSeek', detail)

    def test_create_task_and_update_status(self) -> None:
        text = mcp.create_task(
            '演示项目', '写接口文档', assignee='DeepSeek', detail='契约'
        )
        self.assertIn('已创建任务', text)
        task = self.project.tasks.get(title='写接口文档')
        self.assertEqual(task.assignee, self.member)

        doing = mcp.update_task_status('演示项目', '写接口文档', 'doing')
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DOING)
        self.assertIn('进行中', doing)
        with self.assertRaisesMessage(mcp.McpError, '确认'):
            mcp.update_task_status('演示项目', '写接口文档', 'done')
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DOING)

    def test_add_library_entry(self) -> None:
        mcp.add_library_entry('演示项目', '先做 P0', '范围', 'rule')
        entry = LibraryEntry.objects.get(title='先做 P0')
        self.assertEqual(entry.kind, LibraryEntry.Kind.RULE)

    def test_unknown_project_raises(self) -> None:
        with self.assertRaises(mcp.McpError):
            mcp.get_project('不存在的项目')

    def test_call_tool_dispatch(self) -> None:
        self.assertIn('演示项目', mcp.call_tool('list_projects', {}))
        with self.assertRaises(mcp.McpError):
            mcp.call_tool('nope', {})


class ConnectPageTests(TestCase):
    def test_page_shows_config_and_tools(self) -> None:
        response = self.client.get(reverse('projects:connect'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('mcpServers', html)
        self.assertIn('update_task_status', html)
        self.assertIn('mcp_server.py', html)


class McpLoopTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='Loop', goal_title='上线')
        self.external = Member.objects.create(
            project=self.project,
            kind=Member.Kind.EXTERNAL,
            tool='workbuddy',
            name='WorkBuddy',
            role='执行',
        )
        self.reviewer = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='DeepSeek',
            role='评审',
            key_ciphertext=crypto.protect('sk-test'),
        )
        self.task = Task.objects.create(
            project=self.project,
            title='改登录页',
            detail='把按钮换成绿色',
            assignee=self.external,
        )

    def test_next_task_returns_detail(self) -> None:
        text = mcp.next_task('Loop', 'WorkBuddy')
        self.assertIn('改登录页', text)
        self.assertIn('把按钮换成绿色', text)

    def test_claim_task_marks_doing(self) -> None:
        mcp.claim_task('Loop', '改登录页')
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DOING)

    def test_submit_result_writes_delivery_artifact_and_skips_review(self) -> None:
        with mock.patch('apps.projects.views._run_job'):
            text = mcp.submit_result(
                'Loop',
                '改登录页',
                '按钮已换成绿色',
                '改了 login.css 和 Login.tsx',
                'workbuddy',
            )
        self.assertIn('已记录', text)
        self.assertIn('不自动审核', text)
        self.assertFalse(ReplyJob.objects.filter(project=self.project).exists())

        message = ChatMessage.objects.get(project=self.project)
        self.assertEqual(message.payload.get('source'), 'external-delivery')
        entry = LibraryEntry.objects.get(project=self.project, title='改登录页 · 交付')
        self.assertEqual(entry.kind, LibraryEntry.Kind.ARTIFACT)

    @override_settings(WORKROOM_MODE='server')
    def test_submit_high_risk_creates_review(self) -> None:
        self.task.execution_spec = {'risk': 'high'}
        self.task.save(update_fields=['execution_spec'])
        with mock.patch('apps.projects.views._run_job'):
            text = mcp.submit_result(
                'Loop', '改登录页', '已改权限校验', '改了 auth.py', 'workbuddy'
            )
        self.assertIn('审核', text)
        job = ReplyJob.objects.get(project=self.project)
        self.assertEqual(job.mode, ReplyJob.Mode.REVIEW)
        self.assertEqual(job.member, self.reviewer)

    @override_settings(WORKROOM_MODE='server')
    def test_submit_can_force_review(self) -> None:
        with mock.patch('apps.projects.views._run_job'):
            mcp.submit_result(
                'Loop', '改登录页', '按钮已换', '', 'workbuddy', review=True
            )
        job = ReplyJob.objects.get(project=self.project)
        self.assertEqual(job.mode, ReplyJob.Mode.REVIEW)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DOING)

    def test_add_library_entry_marks_external_source(self) -> None:
        mcp.add_library_entry('Loop', '先做 P0', '范围', 'rule', '一期', '范围')
        entry = LibraryEntry.objects.get(project=self.project, title='先做 P0')
        self.assertEqual(entry.source, LibraryEntry.Source.EXTERNAL)
        self.assertEqual(entry.summary, '一期')
        self.assertEqual(entry.tag_list, ['范围'])


class InboxTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='Inbox', goal_title='上线')
        self.external = Member.objects.create(
            project=self.project,
            kind=Member.Kind.EXTERNAL,
            tool='workbuddy',
            name='WorkBuddy',
            role='执行',
        )
        self.ai = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='DeepSeek',
            key_ciphertext=crypto.protect('sk-test'),
        )
        self.task = Task.objects.create(
            project=self.project,
            title='改登录页',
            detail='按钮换绿色',
            assignee=self.external,
        )

    def test_chat_mention_is_recorded(self) -> None:
        with mock.patch('apps.projects.views._start_job'):
            self.client.post(
                reverse('projects:chat_send', args=[self.project.pk]),
                {'message': '@WorkBuddy 看一下登录页'},
            )
        message = ChatMessage.objects.filter(
            project=self.project, role=ChatMessage.Role.USER
        ).last()
        self.assertIn(self.external.pk, (message.payload or {}).get('mentions', []))

    def test_inbox_lists_mention_until_reply(self) -> None:
        message = ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.USER,
            content='@WorkBuddy 看一下登录页',
            payload={'mentions': [self.external.pk]},
        )
        text = mcp.get_inbox('Inbox', 'WorkBuddy')
        self.assertIn(f'#{message.pk}', text)
        self.assertIn('改登录页', text)

        mcp.post_message('Inbox', '收到，正在看', 'workbuddy')
        text = mcp.get_inbox('Inbox', 'WorkBuddy')
        self.assertNotIn('看一下登录页', text)

    def test_post_message_uses_external_identity(self) -> None:
        result = mcp.post_message('Inbox', '我建议先改按钮颜色', 'workbuddy')
        self.assertIn('WorkBuddy', result)
        message = ChatMessage.objects.filter(
            project=self.project, role=ChatMessage.Role.ASSISTANT
        ).last()
        self.assertEqual(message.member, self.external)
        self.assertEqual(message.payload.get('source'), 'external-chat')

    def test_external_mention_skips_ai_reply(self) -> None:
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(
                reverse('projects:chat_send', args=[self.project.pk]),
                {'message': '@WorkBuddy 看一下登录页', 'ai': self.ai.pk},
            )
        start.assert_not_called()
        self.assertTrue(
            ChatMessage.objects.filter(
                project=self.project,
                role=ChatMessage.Role.SYSTEM,
                content__contains='收件箱',
            ).exists()
        )

    def test_ai_mention_routes_to_that_ai(self) -> None:
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(
                reverse('projects:chat_send', args=[self.project.pk]),
                {'message': '@DeepSeek 看一下登录页'},
            )
        self.assertTrue(start.called)
        self.assertEqual(start.call_args.args[1], self.ai)

    def test_stop_request_is_consumed_once(self) -> None:
        ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.SYSTEM,
            content='已请求停止',
            payload={'control': 'stop', 'member': self.external.pk, 'consumed': False},
        )
        first = mcp.get_inbox('Inbox', 'WorkBuddy')
        self.assertIn('收到停止请求', first)
        second = mcp.get_inbox('Inbox', 'WorkBuddy')
        self.assertNotIn('收到停止请求', second)

    def test_wait_for_work_returns_pending_mention(self) -> None:
        ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.USER,
            content='@WorkBuddy 看一下',
            payload={'mentions': [self.external.pk]},
        )
        text = mcp.wait_for_work('Inbox', 'WorkBuddy', 5)
        self.assertIn('待回复的 @', text)

    def test_report_progress_posts_staged_message(self) -> None:
        mcp.report_progress('Inbox', '改登录页', 'doing', '改完按钮样式', 'workbuddy')
        message = ChatMessage.objects.filter(
            project=self.project, role=ChatMessage.Role.ASSISTANT
        ).last()
        self.assertTrue(message.content.startswith('【进展】'))
        self.assertEqual(message.payload.get('stage'), '进展')

    def test_member_stop_creates_control_message(self) -> None:
        response = self.client.post(
            reverse('projects:member_stop', args=[self.project.pk, self.external.pk])
        )
        self.assertEqual(response.status_code, 302)
        control = ChatMessage.objects.filter(
            project=self.project, payload__control='stop'
        ).first()
        self.assertEqual(control.payload.get('member'), self.external.pk)
        self.assertFalse(control.payload.get('consumed'))


class ToolScopeTests(TestCase):
    def test_wait_and_progress_are_exposed_to_tokens(self) -> None:
        from apps.projects import tool_api

        self.assertIn('wait_for_work', tool_api.READ_TOOLS)
        self.assertIn('report_progress', tool_api.EXECUTE_TOOLS)
