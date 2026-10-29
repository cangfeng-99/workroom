"""Phase-1 checks: tree layout, chat draft, confirm-to-tree, status update."""

from __future__ import annotations

from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.projects import ai_client, crypto, views
from apps.projects.models import (
    ChatMessage,
    LibraryEntry,
    Member,
    Project,
    ReplyJob,
    Task,
)
from apps.projects.tree import NODE_WIDTH, build_tree


class TreeLayoutTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        self.root = Task.objects.create(project=self.project, title='登录模块')
        self.child_a = Task.objects.create(
            project=self.project, title='接口', parent=self.root
        )
        self.child_b = Task.objects.create(
            project=self.project, title='页面', parent=self.root
        )

    def test_goal_is_right_of_every_task(self) -> None:
        tree = build_tree(self.project.tasks.all())
        goal_x = tree['goal']['x']
        self.assertTrue(
            all(node['x'] + NODE_WIDTH <= goal_x for node in tree['nodes'])
        )

    def test_child_sits_right_of_parent(self) -> None:
        tree = build_tree(self.project.tasks.all())
        x = {node['task'].pk: node['x'] for node in tree['nodes']}
        self.assertGreater(x[self.child_a.pk], x[self.root.pk])

    def test_parent_sits_above_children(self) -> None:
        tree = build_tree(self.project.tasks.all())
        y = {node['task'].pk: node['y'] for node in tree['nodes']}
        self.assertLess(y[self.root.pk], y[self.child_a.pk])
        self.assertLess(y[self.root.pk], y[self.child_b.pk])

    def test_empty_project_has_only_the_goal(self) -> None:
        empty = Project.objects.create(name='空', goal_title='目标')
        tree = build_tree(empty.tasks.all())
        self.assertEqual(tree['nodes'], [])
        self.assertGreater(tree['width'], NODE_WIDTH)


class ProjectPickerTests(TestCase):
    def setUp(self) -> None:
        self.alpha = Project.objects.create(name='甲项目', goal_title='甲目标')
        Member.objects.create(project=self.alpha, kind=Member.Kind.HUMAN, name='我')
        Task.objects.create(
            project=self.alpha, title='甲任务', status=Task.Status.DONE
        )
        Task.objects.create(project=self.alpha, title='甲任务二')
        self.beta = Project.objects.create(name='乙项目', goal_title='乙目标')
        Task.objects.create(project=self.beta, title='乙任务')

    def test_index_lists_every_project_with_progress(self) -> None:
        html = self.client.get(reverse('projects:index')).content.decode('utf-8')
        self.assertIn('甲项目', html)
        self.assertIn('乙项目', html)
        self.assertIn('50%', html)
        self.assertIn('2 项具体任务', html)

    def test_project_page_only_shows_its_own_tasks(self) -> None:
        html = self.client.get(
            reverse('projects:space', args=[self.alpha.pk])
        ).content.decode('utf-8')
        self.assertIn('甲任务', html)
        self.assertNotIn('乙任务', html)
        self.assertIn('新建项目', html)

    def test_progress_helpers(self) -> None:
        self.assertEqual(self.alpha.percent, 50)
        self.assertEqual(self.alpha.task_count, 2)
        self.assertEqual(self.alpha.done_count, 1)
        self.assertEqual(self.alpha.member_count, 1)
        self.assertEqual(self.beta.percent, 0)

    def test_create_lands_on_the_new_project(self) -> None:
        response = self.client.post(
            reverse('projects:index'), {'name': '丙项目', 'goal': '丙目标'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Project.objects.count(), 3)
        project = Project.objects.get(name='丙项目')
        self.assertEqual(response['Location'], reverse('projects:space', args=[project.pk]))
        self.assertEqual(project.members.count(), 2)


class TabAndLibraryTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我', role='负责人'
        )
        Task.objects.create(project=self.project, title='登录模块')
        LibraryEntry.objects.create(
            project=self.project, kind=LibraryEntry.Kind.RULE, title='只做 P0', body='范围'
        )

    def _get(self, tab: str | None = None) -> str:
        url = reverse('projects:space', args=[self.project.pk])
        if tab:
            url = f'{url}?tab={tab}'
        return self.client.get(url).content.decode('utf-8')

    def test_default_tab_is_tasks(self) -> None:
        html = self._get()
        self.assertIn('data-task-outline', html)
        self.assertIn('登录模块', html)
        self.assertNotIn('说需求', html)
        self.assertIn('任务树<span class="tab-count">1</span>', html)

    def test_chat_tab_shows_chat_only(self) -> None:
        html = self._get('chat')
        self.assertIn('说需求', html)
        self.assertNotIn('node-goal', html)

    def test_library_tab_lists_entries_by_kind(self) -> None:
        html = self._get('library')
        self.assertIn('只做 P0', html)
        self.assertIn('规则约束', html)
        self.assertNotIn('node-goal', html)

    def test_unknown_tab_falls_back_to_tasks(self) -> None:
        html = self._get('nope')
        self.assertIn('data-task-outline', html)
        self.assertIn('登录模块', html)

    def test_graph_is_still_available_as_an_explicit_view(self) -> None:
        html = self.client.get(reverse('projects:space', args=[self.project.pk]), {'tab': 'tasks', 'view': 'graph'}).content.decode()
        self.assertIn('node-goal', html)
        self.assertIn('登录模块', html)

    def test_library_add_creates_entry_and_selects_it(self) -> None:
        response = self.client.post(
            reverse('projects:library_add', args=[self.project.pk]),
            {'kind': 'decision', 'title': '先本机 SQLite', 'body': '接口稳定后再换'},
        )
        self.assertEqual(response.status_code, 302)
        entry = LibraryEntry.objects.get(title='先本机 SQLite')
        self.assertEqual(entry.kind, 'decision')
        self.assertIn(f'tab=library&entry={entry.pk}', response['Location'])

    def test_library_add_ignores_blank_title(self) -> None:
        self.client.post(
            reverse('projects:library_add', args=[self.project.pk]),
            {'kind': 'rule', 'title': '  '},
        )
        self.assertEqual(LibraryEntry.objects.count(), 1)

    def test_chat_send_redirects_to_chat_tab(self) -> None:
        response = self.client.post(
            reverse('projects:chat_send', args=[self.project.pk]),
            {'message': '做个登录和看板'},
        )
        self.assertIn('tab=chat', response['Location'])

    def test_apply_redirects_to_tasks_tab(self) -> None:
        self.client.post(
            reverse('projects:chat_send', args=[self.project.pk]),
            {'message': '做个登录和看板'},
        )
        draft = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        response = self.client.post(
            reverse('projects:draft_apply', args=[self.project.pk, draft.pk])
        )
        self.assertIn('tab=tasks', response['Location'])
        self.assertIn('task=', response['Location'])


class MemberConfigTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        self.ai = Member.objects.create(
            project=self.project, kind=Member.Kind.AI, name='AI', role='后端'
        )
        self.url = reverse(
            'projects:member_settings', args=[self.project.pk, self.ai.pk]
        )

    def test_page_renders(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('API Key', response.content.decode('utf-8'))

    def test_save_encrypts_key_and_never_echoes_it(self) -> None:
        response = self.client.post(
            self.url,
            {
                'name': 'AI',
                'duty': 'execute',
                'provider': 'deepseek',
                'model_name': '',
                'base_url': '',
                'api_key': 'sk-secret-123',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.ai.refresh_from_db()
        self.assertRegex(self.ai.key_ciphertext, r'^(dpapi|fernet):v1:')
        self.assertNotIn('sk-secret-123', self.ai.key_ciphertext)
        self.assertEqual(crypto.unprotect(self.ai.key_ciphertext), 'sk-secret-123')
        self.assertEqual(self.ai.model_name, 'deepseek-v4-flash')

        page = self.client.get(self.url).content.decode('utf-8')
        self.assertNotIn('sk-secret-123', page)

    def test_clear_key_removes_it(self) -> None:
        self.ai.key_ciphertext = crypto.protect('sk-x')
        self.ai.save()
        self.client.post(
            self.url,
            {'name': 'AI', 'duty': 'execute', 'provider': 'deepseek', 'api_key': '', 'clear_key': 'on'},
        )
        self.ai.refresh_from_db()
        self.assertEqual(self.ai.key_ciphertext, '')

    def test_identity_is_saved(self) -> None:
        response = self.client.post(
            self.url,
            {
                'name': '程砚',
                'role': '架构师',
                'duty': 'decide',
                'persona': '先看风险与边界，再给方案。',
                'provider': 'deepseek',
                'model_name': '',
                'base_url': '',
                'api_key': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.ai.refresh_from_db()
        self.assertEqual(self.ai.name, '程砚')
        self.assertEqual(self.ai.role, '架构师')
        self.assertEqual(self.ai.persona, '先看风险与边界，再给方案。')

    def test_name_is_required(self) -> None:
        response = self.client.post(
            self.url, {'name': '', 'provider': 'deepseek', 'api_key': ''}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('请填写名称', response.content.decode('utf-8'))

    def test_custom_provider_needs_address(self) -> None:
        response = self.client.post(
            self.url,
            {
                'name': 'AI',
                'duty': 'execute',
                'provider': 'custom',
                'model_name': '',
                'base_url': '',
                'api_key': '',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('必须填接口地址', response.content.decode('utf-8'))
        self.ai.refresh_from_db()
        self.assertEqual(self.ai.provider, '')

    def test_rail_has_delete_button(self) -> None:
        chat = self.client.get(
            reverse('projects:space', args=[self.project.pk]) + '?tab=chat'
        ).content.decode('utf-8')
        self.assertIn('member-del', chat)
        self.assertIn('移出团队', chat)

    def test_delete_returns_to_the_current_tab(self) -> None:
        url = reverse('projects:member_delete', args=[self.project.pk, self.ai.pk])
        response = self.client.post(
            url, {'next': f'/p/{self.project.pk}/?tab=tasks'}
        )
        self.assertEqual(response['Location'], f'/p/{self.project.pk}/?tab=tasks')

    def test_delete_member_hides_it_and_clears_key(self) -> None:
        self.ai.key_ciphertext = crypto.protect('sk-x')
        self.ai.save()
        response = self.client.post(
            reverse('projects:member_delete', args=[self.project.pk, self.ai.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.ai.refresh_from_db()
        self.assertFalse(self.ai.is_active)
        self.assertEqual(self.ai.key_ciphertext, '')
        self.assertEqual(self.client.get(self.url).status_code, 404)

        chat = self.client.get(
            reverse('projects:space', args=[self.project.pk]) + '?tab=chat'
        ).content.decode('utf-8')
        self.assertIn('已把 AI 移出团队', chat)
        self.assertNotIn('member-link', chat)

    def test_human_member_has_no_settings_page(self) -> None:
        human = Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我'
        )
        response = self.client.get(
            reverse('projects:member_settings', args=[self.project.pk, human.pk])
        )
        self.assertEqual(response.status_code, 404)


class ModelChatTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        self.me = Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我', role='负责人'
        )
        self.ai = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='DeepSeek',
            role='后端',
            provider='deepseek',
            model_name='deepseek-v4-flash',
            persona='先看风险，再给方案。',
            key_ciphertext=crypto.protect('sk-test-key'),
        )
        self.url = reverse('projects:chat_send', args=[self.project.pk])

    def _payload(self) -> dict:
        today = date.today().isoformat()
        return {
            'tasks': [
                {
                    'ref': 't1',
                    'parent_ref': None,
                    'title': '登录模块',
                    'detail': '账号密码登录',
                    'start_date': today,
                    'end_date': today,
                    'assignee_id': self.ai.pk,
                    'priority': 'normal',
                }
            ]
        }

    def _job(self, member=None, mode=ReplyJob.Mode.PLAN, text='做个登录模块') -> ReplyJob:
        return ReplyJob.objects.create(
            project=self.project,
            member=member or self.ai,
            prompt=text,
            mode=mode,
        )

    def _second_ai(self) -> Member:
        return Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='智谱 GLM',
            role='测试',
            persona='先想边界。',
            provider='zhipu',
            model_name='glm-4.6',
            key_ciphertext=crypto.protect('sk-zhipu'),
        )

    def test_chat_returns_immediately_with_a_job(self) -> None:
        with mock.patch('apps.projects.views._start_job') as start:
            response = self.client.post(self.url, {'message': '做个登录模块'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(start.called)
        args = start.call_args.args
        self.assertEqual(args[1], self.ai)
        self.assertEqual(args[3], ReplyJob.Mode.CHAT)

    def test_plan_mode_is_explicit(self) -> None:
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(self.url, {'message': '拆一下', 'mode': 'plan'})
        self.assertEqual(start.call_args.args[3], ReplyJob.Mode.PLAN)

    def test_choice_is_saved_to_url_and_cookie(self) -> None:
        other = self._second_ai()
        with mock.patch('apps.projects.views._start_job'):
            response = self.client.post(
                self.url, {'message': '做登录', 'ai': other.pk}
            )
        self.assertIn(f'ai={other.pk}', response['Location'])
        self.assertEqual(
            response.cookies[f'ai_{self.project.pk}'].value, str(other.pk)
        )

    def test_cookie_restores_the_choice(self) -> None:
        other = self._second_ai()
        self.client.cookies[f'ai_{self.project.pk}'] = str(other.pk)
        url = reverse('projects:space', args=[self.project.pk])
        html = self.client.get(f'{url}?tab=chat').content.decode('utf-8')
        self.assertIn(f'value="{other.pk}" checked', html)

    def test_all_mode_saves_group_choice(self) -> None:
        self._second_ai()
        with mock.patch('apps.projects.views._start_job'):
            response = self.client.post(
                self.url, {'message': '讨论一下', 'ai': 'all'}
            )
        self.assertEqual(response.cookies[f'ai_{self.project.pk}'].value, 'all')

    def test_chosen_ai_is_used_for_the_job(self) -> None:
        other = self._second_ai()
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(self.url, {'message': '做个登录模块', 'ai': other.pk})
        self.assertEqual(start.call_args.args[1], other)

    def test_plan_job_writes_a_draft(self) -> None:
        job = self._job()
        with mock.patch(
            'apps.projects.views.ai_client.fetch_plan', return_value=self._payload()
        ) as fetch:
            views._run_job(job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, ReplyJob.Status.DONE)
        self.assertEqual(fetch.call_args.kwargs['api_key'], 'sk-test-key')
        self.assertEqual(fetch.call_args.kwargs['model'], 'deepseek-v4-flash')
        passed = fetch.call_args.kwargs['members']
        self.assertTrue(any(m['persona'] == '先看风险，再给方案。' for m in passed))
        message = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.assertEqual(message.member, self.ai)
        self.assertEqual(len(message.draft_tasks), 1)

    def test_all_mode_starts_one_discussion_job(self) -> None:
        self._second_ai()
        with mock.patch('apps.projects.views._start_job') as start:
            response = self.client.post(self.url, {'message': '讨论一下', 'ai': 'all'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('ai=all', response['Location'])
        self.assertEqual(start.call_count, 1)
        args = start.call_args.args
        self.assertIsNone(args[1])
        self.assertEqual(args[3], ReplyJob.Mode.DISCUSS)

    def test_discussion_runs_proposal_review_decision(self) -> None:
        self.ai.duty = Member.Duty.PROPOSE
        self.ai.save()
        reviewer = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='评审员',
            role='测试',
            duty=Member.Duty.REVIEW,
            provider='zhipu',
            model_name='glm-4.6',
            key_ciphertext=crypto.protect('sk-review'),
        )
        decider = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='决策者',
            role='负责人',
            duty=Member.Duty.DECIDE,
            provider='deepseek',
            model_name='deepseek-v4-flash',
            key_ciphertext=crypto.protect('sk-decide'),
        )
        job = ReplyJob.objects.create(
            project=self.project,
            prompt='这个版本做什么',
            mode=ReplyJob.Mode.DISCUSS,
        )

        def fake_stream(**kwargs):
            system = kwargs['messages'][0]['content']
            if '提议阶段' in system:
                yield 'content', '先做同步'
            elif '评审阶段' in system:
                yield 'content', '冲突处理风险最大'
            else:
                yield 'content', ('【已达成一致】\n结论：先做同步，冲突留到二期\n'
                                  '依据：本次范围\n反方意见：冲突处理风险最大\n'
                                  '未解决：二期处理方案\n置信度：中')

        with mock.patch(
            'apps.projects.views.ai_client.stream_messages', side_effect=fake_stream
        ) as stream, mock.patch(
            'apps.projects.views.ai_client.fetch_plan', return_value=self._payload()
        ) as plan:
            views._run_job(job.pk)

        self.assertEqual(stream.call_count, 3)
        self.assertTrue(plan.called)
        messages = list(
            ChatMessage.objects.filter(role=ChatMessage.Role.ASSISTANT).order_by('id')
        )
        self.assertEqual(len(messages), 4)
        self.assertEqual(
            [m.payload.get('phase') for m in messages[:3]],
            ['proposal', 'review', 'decision'],
        )
        self.assertEqual(len(messages[-1].draft_tasks), 1)
        self.assertEqual(messages[-1].payload['source'], 'discussion-draft')
        self.assertEqual(
            [m.member_id for m in messages[:3]],
            [self.ai.pk, reviewer.pk, decider.pk],
        )
        self.assertEqual(
            [m.phase_label for m in messages[:3]], ['提议', '评审', '决策']
        )
        job.refresh_from_db()
        self.assertEqual(job.status, ReplyJob.Status.DONE)

    def test_cancelled_job_never_calls_the_model(self) -> None:
        job = self._job()
        job.status = ReplyJob.Status.CANCELLED
        job.save()
        with mock.patch('apps.projects.views.ai_client.fetch_plan') as fetch:
            views._run_job(job.pk)
        self.assertFalse(fetch.called)
        self.assertEqual(
            ChatMessage.objects.filter(role=ChatMessage.Role.ASSISTANT).count(), 0
        )

    def test_cancel_view_marks_the_job(self) -> None:
        job = self._job()
        response = self.client.post(
            reverse('projects:job_cancel', args=[self.project.pk, job.pk])
        )
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, ReplyJob.Status.CANCELLED)

    def test_status_endpoint_counts_running_jobs(self) -> None:
        self._job()
        response = self.client.get(
            reverse('projects:job_status', args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['running'], 1)

    def test_job_failure_is_written_as_a_message(self) -> None:
        job = self._job()
        with mock.patch(
            'apps.projects.views.ai_client.fetch_plan',
            side_effect=ai_client.PlannerClientError('auth'),
        ):
            views._run_job(job.pk)
        message = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.assertIn('失败', message.content)
        self.assertIn('401', message.content)

    def test_group_job_stores_and_renders_reasoning(self) -> None:
        job = self._job(mode=ReplyJob.Mode.CHAT)

        def fake_stream(**kwargs):
            yield 'reasoning', '先看边界，再看失败路径。'
            yield 'content', '结论是这样。'

        with mock.patch(
            'apps.projects.views.ai_client.stream_reply', side_effect=fake_stream
        ):
            views._run_job(job.pk)
        message = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.assertEqual(message.reasoning, '先看边界，再看失败路径。')
        self.assertEqual(message.reasoning_label, '思考过程')
        url = reverse('projects:space', args=[self.project.pk])
        html = self.client.get(f'{url}?tab=chat').content.decode('utf-8')
        self.assertIn('思考过程', html)
        self.assertIn('先看边界', html)

    def test_pending_job_is_rendered_with_stop_button(self) -> None:
        job = self._job()
        job.phase = 'thinking'
        job.save()
        url = reverse('projects:space', args=[self.project.pk])
        html = self.client.get(f'{url}?tab=chat').content.decode('utf-8')
        self.assertIn('正在思考', html)
        self.assertIn('停止', html)

    def test_add_member_creates_and_starts_identity(self) -> None:
        with mock.patch('apps.projects.views._start_job') as start:
            response = self.client.post(
                reverse('projects:member_create', args=[self.project.pk]),
                {
                    'name': 'Kimi',
                    'provider': 'deepseek',
                    'model_name': '',
                    'base_url': '',
                    'api_key': 'sk-kimi',
                },
            )
        self.assertEqual(response.status_code, 302)
        member = Member.objects.get(name='Kimi')
        self.assertTrue(member.has_key)
        self.assertEqual(start.call_args.args[1], member)
        self.assertEqual(start.call_args.args[3], ReplyJob.Mode.IDENTITY)

    def test_identity_job_updates_member_and_posts_intro(self) -> None:
        member = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='Kimi',
            provider='deepseek',
            model_name='deepseek-v4-flash',
            key_ciphertext=crypto.protect('sk-kimi'),
        )
        job = ReplyJob.objects.create(
            project=self.project,
            member=member,
            prompt='',
            mode=ReplyJob.Mode.IDENTITY,
        )
        with mock.patch(
            'apps.projects.views.ai_client.fetch_identity',
            return_value={
                'role': '测试',
                'duty': 'review',
                'persona': '先想边界。',
                'intro': '我是 Kimi，负责测试。',
            },
        ):
            views._run_job(job.pk)

        member.refresh_from_db()
        self.assertEqual(member.role, '测试')
        self.assertEqual(member.duty, Member.Duty.REVIEW)
        self.assertEqual(member.persona, '先想边界。')
        message = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.assertIn('我是 Kimi', message.content)

    def test_swap_identity_command_swaps_roles(self) -> None:
        other = self._second_ai()
        self.ai.role = '后端'
        self.ai.duty = Member.Duty.PROPOSE
        self.ai.persona = '负责后端'
        self.ai.save()
        other.role = '测试'
        other.duty = Member.Duty.REVIEW
        other.persona = '负责测试'
        other.save()

        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(
                self.url,
                {'message': f'把 {self.ai.name} 和 {other.name} 的身份互换'},
            )

        self.assertFalse(start.called)
        self.ai.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.ai.role, '测试')
        self.assertEqual(self.ai.duty, Member.Duty.REVIEW)
        self.assertEqual(self.ai.persona, '负责测试')
        self.assertEqual(other.role, '后端')
        notice = ChatMessage.objects.get(role=ChatMessage.Role.SYSTEM)
        self.assertIn('已互换', notice.content)

    def test_set_duty_command(self) -> None:
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(
                self.url, {'message': f'让 {self.ai.name} 做决策'}
            )
        self.assertFalse(start.called)
        self.ai.refresh_from_db()
        self.assertEqual(self.ai.duty, Member.Duty.DECIDE)

    def test_system_notice_is_rendered(self) -> None:
        ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.SYSTEM,
            content='已互换 A 和 B 的身份与职责。',
        )
        url = reverse('projects:space', args=[self.project.pk])
        html = self.client.get(f'{url}?tab=chat').content.decode('utf-8')
        self.assertIn('sysmsg', html)
        self.assertIn('已互换', html)

    def test_composer_is_multiline(self) -> None:
        url = reverse('projects:space', args=[self.project.pk])
        html = self.client.get(f'{url}?tab=chat').content.decode('utf-8')
        self.assertIn('<textarea name="message"', html)

    def test_without_key_falls_back_to_demo(self) -> None:
        self.ai.key_ciphertext = ''
        self.ai.save()
        with mock.patch('apps.projects.views._start_job') as start:
            self.client.post(self.url, {'message': '做个登录模块'})
        self.assertFalse(start.called)
        message = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.assertEqual(message.payload['source'], 'demo')


class LoopTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        self.me = Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='我', role='负责人'
        )
        self.ai = Member.objects.create(
            project=self.project, kind=Member.Kind.AI, name='DeepSeek', role='后端'
        )

    def _send(self, text: str = '做一个登录模块和任务看板，两周上线'):
        return self.client.post(
            reverse('projects:chat_send', args=[self.project.pk]), {'message': text}
        )

    def test_chat_saves_turns_and_a_draft(self) -> None:
        response = self._send()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ChatMessage.objects.filter(role=ChatMessage.Role.USER).count(), 1)
        draft = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.assertTrue(draft.draft_tasks)
        self.assertIn('演示响应', draft.content)

    def test_blank_message_creates_nothing(self) -> None:
        self._send('   ')
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_confirm_creates_tree_and_is_idempotent(self) -> None:
        self._send()
        draft = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        url = reverse('projects:draft_apply', args=[self.project.pk, draft.pk])

        first = self.client.post(url)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(Task.objects.count(), len(draft.draft_tasks))
        self.assertTrue(Task.objects.filter(parent__isnull=False).exists())
        draft.refresh_from_db()
        self.assertIsNotNone(draft.applied_at)

        self.client.post(url)
        self.assertEqual(Task.objects.count(), len(draft.draft_tasks))

    def test_repeat_request_never_duplicates_titles(self) -> None:
        self._send()
        draft = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.client.post(
            reverse('projects:draft_apply', args=[self.project.pk, draft.pk])
        )
        count = Task.objects.count()

        self._send()
        second = ChatMessage.objects.filter(role=ChatMessage.Role.ASSISTANT).last()
        titles = [item['title'] for item in second.draft_tasks]
        self.assertNotIn('登录模块', titles)
        self.assertIn('验收与上线', titles)

        self.client.post(
            reverse('projects:draft_apply', args=[self.project.pk, second.pk])
        )
        self.assertEqual(Task.objects.count(), count + len(titles))
        all_titles = list(Task.objects.values_list('title', flat=True))
        self.assertEqual(len(all_titles), len(set(all_titles)))

    def test_confirmed_tasks_append_after_existing_ones(self) -> None:
        Task.objects.create(project=self.project, title='旧任务', order=7)
        self._send()
        draft = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
        self.client.post(
            reverse('projects:draft_apply', args=[self.project.pk, draft.pk])
        )
        first_new = Task.objects.get(title='登录模块')
        self.assertGreater(first_new.order, 7)

    def test_unknown_assignee_is_not_attached(self) -> None:
        other = Project.objects.create(name='另一个', goal_title='别的')
        stranger = Member.objects.create(
            project=other, kind=Member.Kind.AI, name='别人家的 AI'
        )
        message = ChatMessage.objects.create(
            project=self.project,
            role=ChatMessage.Role.ASSISTANT,
            content='draft',
            payload={
                'tasks': [
                    {
                        'ref': 't1',
                        'parent_ref': None,
                        'title': '任务',
                        'assignee_id': stranger.pk,
                    }
                ]
            },
        )
        self.client.post(
            reverse('projects:draft_apply', args=[self.project.pk, message.pk])
        )
        task = Task.objects.get()
        self.assertIsNone(task.assignee)

    def test_status_can_be_changed_from_the_panel(self) -> None:
        task = Task.objects.create(project=self.project, title='登录模块')
        response = self.client.post(
            reverse('projects:task_status', args=[self.project.pk, task.pk]),
            {'status': Task.Status.DONE},
        )
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DONE)

    def test_space_renders_team_and_tree(self) -> None:
        Task.objects.create(project=self.project, title='登录模块', assignee=self.ai)
        response = self.client.get(reverse('projects:space', args=[self.project.pk]))
        html = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('任务树', html)
        self.assertIn('DeepSeek', html)
        self.assertIn('登录模块', html)
        self.assertNotIn('说需求', html)
        self.assertEqual(html.count('tab-count'), 2)

    def test_status_rejects_unknown_value(self) -> None:
        task = Task.objects.create(project=self.project, title='登录模块')
        self.client.post(
            reverse('projects:task_status', args=[self.project.pk, task.pk]),
            {'status': 'nonsense'},
        )
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.TODO)

    def test_index_creates_project_with_default_team(self) -> None:
        response = self.client.post(
            reverse('projects:index'), {'name': '开发项目', 'goal': 'v1 上线'}
        )
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name='开发项目')
        self.assertEqual(project.members.count(), 2)
        self.assertEqual(project.goal_title, 'v1 上线')
