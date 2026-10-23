"""T018 project space contracts: setup, activity, plan/tasks and assets."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from workspaces import grants

from projects.models import Project, ProjectMember, ProjectMessage, TaskNode


class HubTestBase(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'project root'
        self.root.mkdir()
        self.other_root = self.base / 'other'
        self.other_root.mkdir()
        User = get_user_model()
        self.alice = User.objects.create_user('alice')
        self.bob = User.objects.create_user('bob')
        self.carol = User.objects.create_user('carol')
        self.client = Client()
        self.client.force_login(self.alice)

    def make_project(self, name: str = '甲项目', owner=None, path: str = '') -> Project:
        project = Project.objects.create(
            owner=owner or self.alice, name=name, workspace_path=path
        )
        ProjectMember.objects.create(
            project=project,
            kind=ProjectMember.Kind.HUMAN,
            user=project.owner,
            role='项目负责人',
        )
        return project

    def add_human(self, project, user, role='前端') -> ProjectMember:
        return ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN, user=user, role=role
        )

    def add_task(self, project, title='任务', **overrides) -> TaskNode:
        data = {'start_date': '2026-10-01', 'end_date': '2026-10-08'}
        data.update(overrides)
        return TaskNode.objects.create(project=project, title=title, **data)

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def hub_url(self, project) -> str:
        return f'/projects/{project.pk}/space/'

    def grant(self, client, project, root=None) -> None:
        session = client.session
        session[grants.SESSION_KEY] = {
            'root': str(root or self.root),
            'grant_id': 'grant-1',
            'user_id': str(self.alice.pk),
            'project_id': str(project.pk),
        }
        session.save()

    def members_payload(self, rows) -> dict[str, str]:
        data = {
            'members-TOTAL_FORMS': str(len(rows)),
            'members-INITIAL_FORMS': '0',
            'members-MIN_NUM_FORMS': '0',
            'members-MAX_NUM_FORMS': '10',
        }
        for index, row in enumerate(rows):
            prefix = f'members-{index}-'
            data[prefix + 'kind'] = row.get('kind', 'human')
            data[prefix + 'username'] = row.get('username', '')
            data[prefix + 'name'] = row.get('name', '')
            data[prefix + 'role'] = row.get('role', '')
        return data

    def create_payload(self, **overrides) -> dict[str, str]:
        data = {'name': '新项目'}
        data.update(overrides)
        return data


class ProjectSetupTests(HubTestBase):
    def test_browser_default_empty_member_rows_are_optional(self) -> None:
        payload = self.members_payload([
            {'kind': 'human', 'username': '', 'name': '', 'role': ''},
            {'kind': 'human', 'username': '', 'name': '', 'role': ''},
            {'kind': 'human', 'username': '', 'name': '', 'role': ''},
        ])
        response = self.client.post('/projects/new/', {'name': '空团队也可创建', **payload})
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name='空团队也可创建')
        self.assertEqual(project.members.count(), 1)
        self.assertEqual(project.members.get().user_id, self.alice.pk)

    def test_minimal_setup_creates_project_owner_and_no_grant(self) -> None:
        response = self.client.post('/projects/new/', self.create_payload())

        project = Project.objects.get(name='新项目')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'/projects/{project.pk}/space/')
        self.assertEqual(project.instructions, '')
        self.assertEqual(project.workspace_path, '')
        self.assertEqual(project.members.count(), 1)
        self.assertEqual(project.members.get().user, self.alice)
        self.assertNotIn(grants.SESSION_KEY, self.client.session)

    def test_forged_owner_paths_and_grant_fields_are_ignored(self) -> None:
        response = self.client.post('/projects/new/', self.create_payload(
            owner=str(self.bob.pk),
            workspace_path='D:/evil',
            grant_id='forged',
            setup_path=str(self.root),
        ))

        project = Project.objects.get(name='新项目')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(project.owner, self.alice)
        self.assertEqual(project.workspace_path, '')
        self.assertNotIn(grants.SESSION_KEY, self.client.session)

    def test_explicit_authorization_sets_grant_after_creation(self) -> None:
        response = self.client.post('/projects/new/', self.create_payload(
            setup_path=str(self.root),
            authorize_workspace='on',
            workspace_path='D:/evil',
        ))

        project = Project.objects.get(name='新项目')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(project.workspace_path, str(self.root))
        data = self.client.session[grants.SESSION_KEY]
        self.assertEqual(data['root'], str(self.root))
        self.assertEqual(data['project_id'], str(project.pk))
        self.assertEqual(data['user_id'], str(self.alice.pk))
        self.assertNotEqual(data['grant_id'], '')

    def test_invalid_authorized_folder_creates_nothing_and_keeps_grant(self) -> None:
        project = self.make_project('已有项目')
        self.grant(self.client, project)
        old = dict(self.client.session[grants.SESSION_KEY])
        missing = self.base / 'missing'

        response = self.client.post('/projects/new/', self.create_payload(
            name='失败项目', setup_path=str(missing), authorize_workspace='on',
        ))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name='失败项目').exists())
        self.assertEqual(dict(self.client.session[grants.SESSION_KEY]), old)
        self.assertIn('失败项目', response.content.decode('utf-8'))
        self.assertIn('不可用', response.content.decode('utf-8'))

    def test_unchecked_path_does_not_authorize_or_change_current_grant(self) -> None:
        project = self.make_project('已有项目')
        self.grant(self.client, project)
        old = dict(self.client.session[grants.SESSION_KEY])

        response = self.client.post('/projects/new/', self.create_payload(
            setup_path=str(self.other_root),
        ))

        created = Project.objects.get(name='新项目')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(created.workspace_path, '')
        self.assertEqual(dict(self.client.session[grants.SESSION_KEY]), old)

    def test_legacy_link_grant_still_stores_position_without_rebinding(self) -> None:
        session = self.client.session
        session[grants.SESSION_KEY] = {
            'root': str(self.root), 'grant_id': 'standalone',
            'user_id': str(self.alice.pk), 'project_id': '',
        }
        session.save()

        response = self.client.post('/projects/new/', self.create_payload(
            link_grant='on', workspace_path='D:/evil',
        ))

        project = Project.objects.get(name='新项目')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(project.workspace_path, str(self.root))
        self.assertEqual(self.client.session[grants.SESSION_KEY]['project_id'], '')

    def test_initial_team_supports_human_and_ai_roles(self) -> None:
        payload = self.create_payload(**self.members_payload([
            {'kind': 'human', 'username': 'bob', 'role': '前端'},
            {'kind': 'ai', 'name': '设计助手', 'role': '设计'},
        ]))

        response = self.client.post('/projects/new/', payload)

        project = Project.objects.get(name='新项目')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(project.members.count(), 3)
        self.assertEqual(project.members.get(user=self.bob).role, '前端')
        ai = project.members.get(kind=ProjectMember.Kind.AI)
        self.assertEqual(ai.name, '设计助手')
        self.assertIsNone(ai.user)

    def test_owner_and_duplicate_accounts_are_rejected_atomically(self) -> None:
        for rows in (
            [{'kind': 'human', 'username': 'alice'}],
            [{'kind': 'human', 'username': 'bob'}, {'kind': 'human', 'username': 'bob'}],
        ):
            with self.subTest(rows=rows):
                payload = self.create_payload(**self.members_payload(rows))
                response = self.client.post('/projects/new/', payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(Project.objects.filter(name='新项目').exists())
                self.assertIn('alice' if len(rows) == 1 else 'bob',
                              response.content.decode('utf-8'))

    def test_unknown_inactive_and_nameless_ai_members_are_rejected(self) -> None:
        get_user_model().objects.create_user('idle', is_active=False)
        for row in (
            {'kind': 'human', 'username': 'nobody'},
            {'kind': 'human', 'username': 'idle'},
            {'kind': 'ai', 'name': '', 'role': '测试'},
        ):
            with self.subTest(row=row):
                payload = self.create_payload(**self.members_payload([row]))
                response = self.client.post('/projects/new/', payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(Project.objects.filter(name='新项目').exists())

    def test_formset_over_ten_rows_is_rejected(self) -> None:
        rows = [
            {'kind': 'ai', 'name': f'助手{index}', 'role': '测试'}
            for index in range(11)
        ]
        payload = self.create_payload(**self.members_payload(rows))

        response = self.client.post('/projects/new/', payload)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.exists())

    def test_invalid_member_keeps_other_input(self) -> None:
        payload = self.create_payload(
            name='保留项目', description='保留说明',
            **self.members_payload([{'kind': 'human', 'username': 'nobody'}]),
        )

        response = self.client.post('/projects/new/', payload)
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 400)
        self.assertIn('保留项目', html)
        self.assertIn('保留说明', html)
        self.assertIn('nobody', html)


class HubAccessTests(HubTestBase):
    def test_anonymous_redirects_and_stranger_gets_404(self) -> None:
        project = self.make_project()
        self.add_human(project, self.bob)
        other = self.make_project('乙项目', owner=self.carol)

        anonymous = Client().get(self.hub_url(project))
        stranger = self.as_user(self.carol).get(self.hub_url(project))

        self.assertEqual(anonymous.status_code, 302)
        self.assertTrue(anonymous['Location'].startswith('/accounts/login/?next='))
        self.assertEqual(stranger.status_code, 404)
        self.assertEqual(self.client.get(self.hub_url(other)).status_code, 404)

    def test_owner_and_member_read_and_no_store(self) -> None:
        project = self.make_project()
        self.add_human(project, self.bob)

        owner = self.client.get(self.hub_url(project))
        member = self.as_user(self.bob).get(self.hub_url(project))

        self.assertEqual(owner.status_code, 200)
        self.assertTrue(owner.context['is_owner'])
        self.assertEqual(owner.context['active_tab'], 'activity')
        self.assertIn('no-store', owner['Cache-Control'])
        self.assertEqual(member.status_code, 200)
        self.assertFalse(member.context['is_owner'])

    def test_tab_and_view_whitelist(self) -> None:
        project = self.make_project()
        for tab in ('activity', 'plan', 'tasks', 'assets'):
            with self.subTest(tab=tab):
                self.assertEqual(
                    self.client.get(self.hub_url(project), {'tab': tab}).status_code, 200
                )
        self.assertEqual(
            self.client.get(self.hub_url(project), {'view': 'kanban'}).status_code, 200
        )
        for query in ({'tab': 'secret'}, {'tab': ''}, {'view': 'drag'}):
            with self.subTest(query=query):
                self.assertEqual(
                    self.client.get(self.hub_url(project), query).status_code, 404
                )
        self.assertEqual(self.client.post(self.hub_url(project)).status_code, 405)

    def test_project_cards_and_tabs_render_real_entries(self) -> None:
        project = self.make_project('卡片项目')
        joined = self.make_project('参与项目', owner=self.carol)
        self.add_human(joined, self.alice)
        self.add_task(project, '卡片任务')
        ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.AI, name='设计助手', role='设计'
        )

        listing = self.client.get('/projects/').content.decode('utf-8')
        hub = self.client.get(self.hub_url(project)).content.decode('utf-8')

        self.assertIn('我创建的项目', listing)
        self.assertIn('参与的项目', listing)
        self.assertIn(f'/projects/{project.pk}/space/', listing)
        self.assertIn(f'/projects/{joined.pk}/space/', listing)
        for label in ('动态', '计划', '任务', '资产'):
            self.assertIn(label, hub)
        self.assertIn('项目配置', hub)
        self.assertIn('连接器', hub)
        self.assertIn('技能', hub)
        self.assertIn('定时执行', hub)
        self.assertIn('未接入', hub)
        self.assertIn('AI · 未连接', hub)
        self.assertIn(f'/projects/{project.pk}/invitations/', hub)

    def test_member_never_sees_workspace_path(self) -> None:
        project = self.make_project(path=str(self.root))
        self.add_human(project, self.bob)
        bob = self.as_user(self.bob)
        session = bob.session
        session[grants.SESSION_KEY] = {
            'root': str(self.root), 'grant_id': 'g', 'user_id': str(self.bob.pk),
            'project_id': str(project.pk),
        }
        session.save()

        html = bob.get(self.hub_url(project), {'tab': 'assets'}).content.decode('utf-8')

        self.assertNotIn(str(self.root), html)
        self.assertIn('成员不读取本机文件', html)


class HubMessageTests(HubTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.make_project()
        self.bob_member = self.add_human(self.project, self.bob)
        self.url = f'{self.hub_url(self.project)}messages/'

    def test_owner_and_member_publish_real_messages(self) -> None:
        owner = self.client.post(self.url, {'content': '第一版完成'})
        member = self.as_user(self.bob).post(self.url, {'content': '我来补测试'})

        self.assertEqual(owner.status_code, 302)
        self.assertEqual(member.status_code, 302)
        notes = list(ProjectMessage.objects.order_by('pk'))
        self.assertEqual([note.author for note in notes], [self.alice, self.bob])
        self.assertIn('第一版完成', notes[0].content)
        html = self.client.get(self.hub_url(self.project)).content.decode('utf-8')
        self.assertIn('第一版完成', html)
        self.assertIn('alice', html)

    def test_stranger_cannot_post_and_empty_content_is_rejected(self) -> None:
        self.assertEqual(
            self.as_user(self.carol).post(self.url, {'content': 'x'}).status_code, 404
        )
        blank = self.client.post(self.url, {'content': '   '})
        too_long = self.client.post(self.url, {'content': 'x' * 4001})

        self.assertEqual(blank.status_code, 400)
        self.assertEqual(too_long.status_code, 400)
        self.assertFalse(ProjectMessage.objects.exists())

    def test_method_and_csrf_limits(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.alice)
        self.assertEqual(csrf.post(self.url, {'content': 'x'}).status_code, 403)


class HubInstructionsTests(HubTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.make_project()
        self.add_human(self.project, self.bob)
        self.url = f'{self.hub_url(self.project)}instructions/'

    def test_owner_edits_instructions(self) -> None:
        response = self.client.post(self.url, {'instructions': '先写测试再实现。'})

        self.project.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.project.instructions, '先写测试再实现。')
        self.assertIn(
            '先写测试再实现。',
            self.client.get(self.hub_url(self.project)).content.decode('utf-8'),
        )

    def test_member_forbidden_and_stranger_404(self) -> None:
        self.assertEqual(
            self.as_user(self.bob).post(self.url, {'instructions': 'x'}).status_code, 403
        )
        self.assertEqual(
            self.as_user(self.carol).post(self.url, {'instructions': 'x'}).status_code, 404
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.instructions, '')

    def test_too_long_and_method_csrf(self) -> None:
        too_long = self.client.post(self.url, {'instructions': 'x' * 6001})
        self.assertEqual(too_long.status_code, 400)
        self.project.refresh_from_db()
        self.assertEqual(self.project.instructions, '')
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.alice)
        self.assertEqual(csrf.post(self.url, {'instructions': 'x'}).status_code, 403)


class HubTaskTests(HubTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.make_project()

    def test_plan_table_and_kanban_use_real_tasks(self) -> None:
        self.add_task(
            self.project, '接口联调', status=TaskNode.Status.IN_PROGRESS,
            priority=TaskNode.Priority.HIGH, labels='后端',
        )
        self.add_task(self.project, '视觉验收', status=TaskNode.Status.REVIEW)

        table = self.client.get(self.hub_url(self.project), {'tab': 'plan'})
        kanban = self.client.get(
            self.hub_url(self.project), {'tab': 'plan', 'view': 'kanban'}
        )
        html = table.content.decode('utf-8')

        self.assertEqual(table.status_code, 200)
        self.assertIn('标题', html)
        self.assertIn('优先级', html)
        self.assertIn('标签', html)
        self.assertIn('接口联调', html)
        self.assertIn('高', html)
        self.assertIn(f'/projects/{self.project.pk}/board/?task=', html)
        self.assertEqual(kanban.status_code, 200)
        self.assertIn('进行中', kanban.content.decode('utf-8'))

    def test_task_filters_match_title_and_status(self) -> None:
        self.add_task(self.project, '接口联调', description='对接登录')
        self.add_task(self.project, '文案校对', status=TaskNode.Status.DONE)

        by_text = self.client.get(
            self.hub_url(self.project), {'tab': 'tasks', 'q': '登录'}
        )
        by_status = self.client.get(
            self.hub_url(self.project), {'tab': 'tasks', 'status': 'done'}
        )
        no_match = self.client.get(
            self.hub_url(self.project), {'tab': 'tasks', 'q': '不存在'}
        )

        self.assertIn('接口联调', by_text.content.decode('utf-8'))
        self.assertNotIn('文案校对', by_text.content.decode('utf-8'))
        self.assertIn('文案校对', by_status.content.decode('utf-8'))
        self.assertNotIn('接口联调', by_status.content.decode('utf-8'))
        self.assertIn('没有匹配的任务', no_match.content.decode('utf-8'))

    def test_old_post_without_priority_and_labels_keeps_defaults(self) -> None:
        response = self.client.post(
            f'/projects/{self.project.pk}/board/tasks/',
            {
                'title': '旧页面任务', 'description': '', 'status': 'todo',
                'start_date': '2026-10-01', 'end_date': '2026-10-02',
            },
        )

        task = TaskNode.objects.get(project=self.project)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(task.priority, TaskNode.Priority.NORMAL)
        self.assertEqual(task.labels, '')

    def test_old_edit_post_preserves_priority_and_labels(self) -> None:
        task = self.add_task(
            self.project, '保留字段', priority=TaskNode.Priority.URGENT, labels='前端'
        )

        response = self.client.post(
            f'/projects/{self.project.pk}/board/tasks/{task.pk}/',
            {
                'title': '保留字段改名', 'description': '', 'status': 'todo',
                'start_date': '2026-10-01', 'end_date': '2026-10-02',
            },
        )

        task.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(task.title, '保留字段改名')
        self.assertEqual(task.priority, TaskNode.Priority.URGENT)
        self.assertEqual(task.labels, '前端')

    def test_explicit_labels_can_be_cleared_and_priority_changed(self) -> None:
        task = self.add_task(
            self.project, '可清空', priority=TaskNode.Priority.LOW, labels='旧标签'
        )

        response = self.client.post(
            f'/projects/{self.project.pk}/board/tasks/{task.pk}/',
            {
                'title': '可清空', 'description': '', 'status': 'todo',
                'start_date': '2026-10-01', 'end_date': '2026-10-02',
                'labels': '', 'priority': TaskNode.Priority.HIGH,
            },
        )

        task.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(task.labels, '')
        self.assertEqual(task.priority, TaskNode.Priority.HIGH)

    def test_board_new_query_opens_task_dialog(self) -> None:
        page = self.client.get(
            f'/projects/{self.project.pk}/board/', {'new': 'task'}
        )

        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context['open_task_dialog'])
        self.assertIn('data-open-on-load', page.content.decode('utf-8'))


class HubAssetTests(HubTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.make_project(path=str(self.root))
        (self.root / 'brief.pdf').write_bytes(b'%PDF-1.4 secret body')
        (self.root / 'cover.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 10)
        (self.root / 'big.bin').write_bytes(b'x' * (70 * 1024))
        (self.root / 'notes.txt').write_text('editable', encoding='utf-8')
        (self.root / 'sub').mkdir()
        (self.root / 'sub' / 'inside.pdf').write_bytes(b'%PDF inside')

    def test_owner_with_grant_lists_metadata_without_reading_content(self) -> None:
        self.grant(self.client, self.project)

        with mock.patch.object(
            type(self._workspace()), '_read_file', side_effect=AssertionError('read')
        ):
            page = self.client.get(self.hub_url(self.project), {'tab': 'assets'})

        html = page.content.decode('utf-8')
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context['authorized'])
        self.assertIn('brief.pdf', html)
        self.assertIn('PDF', html)
        self.assertIn('cover.png', html)
        self.assertIn('PNG', html)
        self.assertIn('big.bin', html)
        self.assertIn('文件夹', html)
        self.assertNotIn('secret body', html)

    def _workspace(self):
        from workspaces.services import Workspace

        return Workspace(self.root)

    def test_subdirectory_navigation_and_back(self) -> None:
        self.grant(self.client, self.project)

        page = self.client.get(
            self.hub_url(self.project), {'tab': 'assets', 'dir': 'sub'}
        )

        self.assertEqual(page.context['current_dir'], 'sub')
        self.assertIn('inside.pdf', page.content.decode('utf-8'))
        self.assertIn('返回上级', page.content.decode('utf-8'))

    def test_member_with_grant_never_triggers_filesystem(self) -> None:
        self.add_human(self.project, self.bob)
        bob = self.as_user(self.bob)
        session = bob.session
        session[grants.SESSION_KEY] = {
            'root': str(self.root), 'grant_id': 'g', 'user_id': str(self.bob.pk),
            'project_id': str(self.project.pk),
        }
        session.save()

        with mock.patch('projects.hub_views.Workspace') as workspace:
            page = bob.get(self.hub_url(self.project), {'tab': 'assets'})

        workspace.assert_not_called()
        self.assertFalse(page.context['authorized'])
        self.assertNotIn(str(self.root), page.content.decode('utf-8'))

    def test_owner_without_grant_never_triggers_filesystem(self) -> None:
        with mock.patch('projects.hub_views.Workspace') as workspace:
            page = self.client.get(self.hub_url(self.project), {'tab': 'assets'})

        workspace.assert_not_called()
        self.assertFalse(page.context['authorized'])
        self.assertIn('尚未授权', page.content.decode('utf-8'))

    def test_traversal_is_rejected_without_escape(self) -> None:
        self.grant(self.client, self.project)
        outside = self.base / 'outside.pdf'
        outside.write_bytes(b'%PDF outside')

        page = self.client.get(
            self.hub_url(self.project), {'tab': 'assets', 'dir': '..'}
        )

        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context['error'])
        self.assertEqual(page.context['assets'], [])
        self.assertNotIn('outside.pdf', page.content.decode('utf-8'))
        self.assertEqual(outside.read_bytes(), b'%PDF outside')

    def test_link_hardlink_and_hidden_entries_are_skipped(self) -> None:
        self.grant(self.client, self.project)
        sentinel = self.base / 'sentinel.pdf'
        sentinel.write_bytes(b'%PDF do not touch')
        os.link(sentinel, self.root / 'hardlink.pdf')
        (self.root / '.hidden.pdf').write_bytes(b'%PDF hidden')
        try:
            os.symlink(sentinel, self.root / 'linked.pdf')
        except OSError:
            pass

        page = self.client.get(self.hub_url(self.project), {'tab': 'assets'})
        html = page.content.decode('utf-8')

        self.assertNotIn('hardlink.pdf', html)
        self.assertNotIn('.hidden.pdf', html)
        self.assertNotIn('linked.pdf', html)
        self.assertEqual(sentinel.read_bytes(), b'%PDF do not touch')
