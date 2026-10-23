"""T016A board contracts: members, task tree, permissions and canvas data."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from workspaces import grants

from projects.models import Project, ProjectMember, TaskNode


class BoardTestBase(TestCase):
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

    # -- helpers -------------------------------------------------------
    def make_project(self, name: str = '甲项目', owner=None) -> Project:
        project = Project.objects.create(owner=owner or self.alice, name=name)
        ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN, user=project.owner,
            role='项目负责人',
        )
        return project

    def add_human(self, project: Project, user, role: str = '前端') -> ProjectMember:
        return ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN, user=user, role=role
        )

    def add_task(self, project: Project, title: str = '整体任务', parent=None,
                 assignee=None, start='2026-10-01', end='2026-10-10') -> TaskNode:
        return TaskNode.objects.create(
            project=project, title=title, parent=parent, assignee=assignee,
            start_date=start, end_date=end,
        )

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def board_url(self, project: Project) -> str:
        return f'/projects/{project.pk}/board/'

    def task_payload(self, **overrides) -> dict[str, str]:
        data = {
            'title': '页面联调',
            'description': '按日期推进',
            'status': TaskNode.Status.TODO,
            'start_date': '2026-10-02',
            'end_date': '2026-10-05',
        }
        data.update(overrides)
        return data


class BoardAccessTests(BoardTestBase):
    def test_board_read_endpoint_rejects_post(self) -> None:
        project = self.make_project()
        self.assertEqual(self.client.post(self.board_url(project)).status_code, 405)

    def test_anonymous_board_redirects_to_login(self) -> None:
        project = self.make_project()

        response = Client().get(self.board_url(project))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/accounts/login/?next='))

    def test_owner_and_human_member_can_read_board(self) -> None:
        project = self.make_project()
        self.add_human(project, self.bob)

        owner_page = self.client.get(self.board_url(project))
        member_page = self.as_user(self.bob).get(self.board_url(project))

        self.assertEqual(owner_page.status_code, 200)
        self.assertTrue(owner_page.context['is_owner'])
        self.assertEqual(member_page.status_code, 200)
        self.assertFalse(member_page.context['is_owner'])
        self.assertIn('no-store', owner_page['Cache-Control'])

    def test_stranger_and_unrelated_member_get_404(self) -> None:
        project = self.make_project()
        other = self.make_project('乙项目', owner=self.carol)
        self.add_human(other, self.bob)

        self.assertEqual(self.as_user(self.carol).get(self.board_url(project)).status_code, 404)
        self.assertEqual(self.as_user(self.bob).get(self.board_url(project)).status_code, 404)
        self.assertEqual(self.client.get('/projects/9999/board/').status_code, 404)

    def test_visible_projects_cover_owned_and_member_without_duplicates(self) -> None:
        owned = self.make_project('自己的')
        other = self.make_project('别人的', owner=self.carol)
        member_project = self.make_project('参与的', owner=self.carol)
        self.add_human(member_project, self.alice)

        # The owner is also a member row of an owned project; the joined query
        # must not report that project twice.
        page = self.client.get(self.board_url(owned))
        visible = list(page.context['visible_projects'])

        self.assertEqual(
            sorted(p.pk for p in visible), sorted([owned.pk, member_project.pk])
        )
        self.assertNotIn(other.pk, [p.pk for p in visible])
        self.assertEqual(len(visible), len({p.pk for p in visible}))


class MemberManagementTests(BoardTestBase):
    def test_human_display_name_supports_full_auth_username_length(self) -> None:
        project = self.make_project()
        username = 'long_user_' + 'x' * 100
        user = get_user_model().objects.create_user(username)
        response = self.client.post(
            f'{self.board_url(project)}members/',
            {'kind': 'human', 'username': username, 'role': '测试'},
        )
        self.assertEqual(response.status_code, 302)
        member = project.members.get(user=user)
        self.assertEqual(member.name, username)
        member.full_clean()

    def test_owner_adds_existing_human_by_username(self) -> None:
        project = self.make_project()

        response = self.client.post(
            f'{self.board_url(project)}members/',
            {'kind': ProjectMember.Kind.HUMAN, 'username': 'bob', 'role': '前端'},
        )

        self.assertEqual(response.status_code, 302)
        member = ProjectMember.objects.get(project=project, user=self.bob)
        self.assertEqual(member.name, 'bob')
        self.assertEqual(member.role, '前端')

    def test_duplicate_and_unknown_username_are_rejected_without_new_account(self) -> None:
        project = self.make_project()
        self.add_human(project, self.bob)

        duplicate = self.client.post(
            f'{self.board_url(project)}members/',
            {'kind': ProjectMember.Kind.HUMAN, 'username': 'bob', 'role': '后端'},
        )
        unknown = self.client.post(
            f'{self.board_url(project)}members/',
            {'kind': ProjectMember.Kind.HUMAN, 'username': 'nobody', 'role': '后端'},
        )

        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(ProjectMember.objects.filter(project=project).count(), 2)
        self.assertFalse(get_user_model().objects.filter(username='nobody').exists())

    def test_inactive_user_cannot_be_added(self) -> None:
        project = self.make_project()
        inactive = get_user_model().objects.create_user('idle', is_active=False)

        response = self.client.post(
            f'{self.board_url(project)}members/',
            {'kind': ProjectMember.Kind.HUMAN, 'username': 'idle'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ProjectMember.objects.filter(user=inactive).exists())

    def test_ai_member_has_no_user_and_creates_no_account(self) -> None:
        project = self.make_project()

        response = self.client.post(
            f'{self.board_url(project)}members/',
            {
                'kind': ProjectMember.Kind.AI, 'name': '设计助手', 'role': '设计',
                'username': 'alice',
            },
        )

        self.assertEqual(response.status_code, 302)
        member = ProjectMember.objects.get(project=project, kind=ProjectMember.Kind.AI)
        self.assertIsNone(member.user)
        self.assertEqual(member.name, '设计助手')
        self.assertEqual(get_user_model().objects.filter(username='设计助手').count(), 0)

    def test_owner_updates_role_and_member_cannot(self) -> None:
        project = self.make_project()
        member = self.add_human(project, self.bob)
        url = f'{self.board_url(project)}members/{member.pk}/'

        denied = self.as_user(self.bob).post(url, {'role': '负责人'})
        changed = self.client.post(url, {'role': '后端'})

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(changed.status_code, 302)
        member.refresh_from_db()
        self.assertEqual(member.role, '后端')
        self.assertEqual(member.user, self.bob)

    def test_member_endpoints_are_project_scoped(self) -> None:
        project = self.make_project()
        other = self.make_project('乙项目', owner=self.carol)
        foreign_member = other.members.get(user=self.carol)

        response = self.client.post(
            f'{self.board_url(project)}members/{foreign_member.pk}/', {'role': 'x'}
        )

        self.assertEqual(response.status_code, 404)
        foreign_member.refresh_from_db()
        self.assertEqual(foreign_member.role, '项目负责人')


class TaskTests(BoardTestBase):
    def test_owner_creates_task_with_dates_and_assignee(self) -> None:
        project = self.make_project()
        member = self.add_human(project, self.bob)

        response = self.client.post(
            f'{self.board_url(project)}tasks/',
            self.task_payload(assignee=str(member.pk), title='第一层'),
        )

        self.assertEqual(response.status_code, 302)
        task = TaskNode.objects.get(project=project, title='第一层')
        self.assertEqual(task.assignee, member)
        self.assertEqual(str(task.start_date), '2026-10-02')
        self.assertEqual(str(task.end_date), '2026-10-05')

    def test_task_rejects_inverted_or_missing_dates(self) -> None:
        project = self.make_project()

        inverted = self.client.post(
            f'{self.board_url(project)}tasks/',
            self.task_payload(start_date='2026-10-09', end_date='2026-10-01'),
        )
        missing = self.client.post(
            f'{self.board_url(project)}tasks/', self.task_payload(start_date='', end_date='')
        )

        self.assertEqual(inverted.status_code, 400)
        self.assertEqual(missing.status_code, 400)
        self.assertFalse(TaskNode.objects.exists())
        self.assertIn('结束日期', inverted.content.decode('utf-8'))

    def test_task_rejects_parent_and_assignee_from_another_project(self) -> None:
        project = self.make_project()
        other = self.make_project('乙项目', owner=self.carol)
        foreign_task = self.add_task(other)
        foreign_member = other.members.get(user=self.carol)

        bad_parent = self.client.post(
            f'{self.board_url(project)}tasks/',
            self.task_payload(parent=str(foreign_task.pk)),
        )
        bad_assignee = self.client.post(
            f'{self.board_url(project)}tasks/',
            self.task_payload(assignee=str(foreign_member.pk)),
        )

        self.assertEqual(bad_parent.status_code, 400)
        self.assertEqual(bad_assignee.status_code, 400)
        self.assertFalse(TaskNode.objects.filter(project=project).exists())

    def test_owner_updates_fields_but_parent_stays_fixed(self) -> None:
        project = self.make_project()
        parent = self.add_task(project, '整体')
        child = self.add_task(project, '子任务', parent=parent)
        other_parent = self.add_task(project, '另一个整体')

        response = self.client.post(
            f'{self.board_url(project)}tasks/{child.pk}/',
            self.task_payload(title='改过', parent=str(other_parent.pk)),
        )

        self.assertEqual(response.status_code, 302)
        child.refresh_from_db()
        self.assertEqual(child.title, '改过')
        self.assertEqual(child.parent, parent)

    def test_task_update_cannot_assign_member_from_other_project(self) -> None:
        project = self.make_project()
        other = self.make_project('乙项目', owner=self.carol)
        task = self.add_task(project)
        foreign_member = other.members.get(user=self.carol)

        response = self.client.post(
            f'{self.board_url(project)}tasks/{task.pk}/',
            self.task_payload(assignee=str(foreign_member.pk)),
        )

        self.assertEqual(response.status_code, 400)
        task.refresh_from_db()
        self.assertIsNone(task.assignee)

    def test_cross_project_task_url_is_404(self) -> None:
        project = self.make_project()
        other = self.make_project('乙项目', owner=self.carol)
        foreign_task = self.add_task(other)

        response = self.client.post(
            f'{self.board_url(project)}tasks/{foreign_task.pk}/', self.task_payload()
        )

        self.assertEqual(response.status_code, 404)
        foreign_task.refresh_from_db()
        self.assertEqual(foreign_task.title, '整体任务')

    def test_edit_query_only_accepts_tasks_of_this_project(self) -> None:
        project = self.make_project()
        task = self.add_task(project, '本任务')
        other = self.make_project('乙项目', owner=self.carol)
        foreign_task = self.add_task(other)

        page = self.client.get(f'{self.board_url(project)}?task={task.pk}')
        denied = self.client.get(f'{self.board_url(project)}?task={foreign_task.pk}')
        malformed = self.client.get(f'{self.board_url(project)}?task=abc')

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['editing_task'], task)
        self.assertIsNotNone(page.context['edit_form'])
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(malformed.status_code, 404)


class MemberTaskPermissionTests(BoardTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.make_project()
        self.member = self.add_human(self.project, self.bob)
        self.own = self.add_task(self.project, '我的任务', assignee=self.member)
        self.other = self.add_task(self.project, '别人的任务')
        self.bob_client = self.as_user(self.bob)

    def test_member_can_only_change_own_task_status(self) -> None:
        url = f'{self.board_url(self.project)}tasks/{self.own.pk}/'

        changed = self.bob_client.post(url, {'status': TaskNode.Status.IN_PROGRESS})
        smuggled = self.bob_client.post(
            url, {'status': TaskNode.Status.DONE, 'title': '被篡改', 'end_date': '2030-01-01'}
        )

        self.assertEqual(changed.status_code, 302)
        self.assertEqual(smuggled.status_code, 302)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, TaskNode.Status.DONE)
        self.assertEqual(self.own.title, '我的任务')
        self.assertEqual(str(self.own.end_date), '2026-10-10')

    def test_member_cannot_change_other_or_unassigned_task(self) -> None:
        for task in (self.other,):
            response = self.bob_client.post(
                f'{self.board_url(self.project)}tasks/{task.pk}/',
                {'status': TaskNode.Status.DONE},
            )
            self.assertEqual(response.status_code, 403, task.pk)

        self.other.refresh_from_db()
        self.assertEqual(self.other.status, TaskNode.Status.TODO)

    def test_member_cannot_manage_structure_members_or_workspace(self) -> None:
        board = self.board_url(self.project)

        self.assertEqual(
            self.bob_client.post(f'{board}tasks/', self.task_payload()).status_code, 403
        )
        self.assertEqual(
            self.bob_client.post(
                f'{board}members/', {'kind': 'human', 'username': 'carol'}
            ).status_code, 403
        )
        self.assertEqual(
            self.bob_client.post(f'{board}workspace/', {'path': str(self.root)}).status_code,
            403,
        )
        self.assertEqual(TaskNode.objects.filter(project=self.project).count(), 2)
        self.project.refresh_from_db()
        self.assertEqual(self.project.workspace_path, '')
        self.assertNotIn(grants.SESSION_KEY, self.bob_client.session)

    def test_member_get_hides_workspace_path_and_grants(self) -> None:
        self.project.workspace_path = str(self.root)
        self.project.save(update_fields=['workspace_path'])

        page = self.bob_client.get(self.board_url(self.project))
        html = page.content.decode('utf-8')

        self.assertEqual(page.status_code, 200)
        self.assertNotIn(str(self.root), html)
        self.assertNotIn('workspace_path', html)
        self.assertIsNone(page.context['workspace_form'])
        self.assertNotIn(grants.SESSION_KEY, self.bob_client.session)


class WorkspaceActionTests(BoardTestBase):
    def test_owner_explicitly_authorizes_existing_folder(self) -> None:
        project = self.make_project()
        url = f'{self.board_url(project)}workspace/'

        response = self.client.post(url, {'path': str(self.root)})

        self.assertEqual(response.status_code, 302)
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, str(self.root))
        grant = self.client.session[grants.SESSION_KEY]
        self.assertEqual(grant['root'], str(self.root))
        self.assertEqual(grant['project_id'], str(project.pk))
        self.assertEqual(grant['user_id'], str(self.alice.pk))

    def test_invalid_folder_keeps_previous_location_and_grant(self) -> None:
        project = self.make_project()
        project.workspace_path = str(self.root)
        project.save(update_fields=['workspace_path'])
        self.client.post(f'{self.board_url(project)}workspace/', {'path': str(self.root)})
        old_grant = dict(self.client.session[grants.SESSION_KEY])
        missing = self.base / 'missing'

        response = self.client.post(
            f'{self.board_url(project)}workspace/', {'path': str(missing)}
        )

        self.assertEqual(response.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, str(self.root))
        self.assertEqual(dict(self.client.session[grants.SESSION_KEY]), old_grant)

    def test_get_never_authorizes_or_writes(self) -> None:
        project = self.make_project()

        page = self.client.get(
            f'{self.board_url(project)}?path={self.root}'
        )

        self.assertEqual(page.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, '')
        self.assertNotIn(grants.SESSION_KEY, self.client.session)
        self.assertEqual(
            self.client.get(f'{self.board_url(project)}workspace/').status_code, 405
        )


class MethodAndCsrfTests(BoardTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.make_project()
        self.task = self.add_task(self.project, '任务')
        self.member = self.add_human(self.project, self.bob)
        self.post_urls = [
            f'{self.board_url(self.project)}members/',
            f'{self.board_url(self.project)}members/{self.member.pk}/',
            f'{self.board_url(self.project)}tasks/',
            f'{self.board_url(self.project)}tasks/{self.task.pk}/',
            f'{self.board_url(self.project)}workspace/',
        ]

    def test_post_endpoints_reject_get(self) -> None:
        for url in self.post_urls:
            self.assertEqual(self.client.get(url).status_code, 405, url)

    def test_post_endpoints_require_csrf(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.alice)
        for url in self.post_urls:
            self.assertEqual(csrf_client.post(url, {}).status_code, 403, url)
        self.assertEqual(TaskNode.objects.count(), 1)
        self.assertEqual(ProjectMember.objects.filter(project=self.project).count(), 2)


class BoardContextTests(BoardTestBase):
    def test_canvas_data_shape_labels_and_json_script(self) -> None:
        project = self.make_project()
        member = self.add_human(project, self.bob, role='后端')
        task = self.add_task(project, '画布任务', assignee=member)
        task.description = '内容'
        task.status = TaskNode.Status.REVIEW
        task.save()

        page = self.client.get(self.board_url(project))
        canvas = page.context['canvas_data']
        html = page.content.decode('utf-8')

        self.assertEqual(canvas['project'], {
            'id': project.pk, 'name': project.name, 'description': '',
        })
        self.assertEqual(
            canvas['members'][0],
            {'id': project.members.get(user=self.alice).pk, 'name': 'alice',
             'kind': 'human', 'role': '项目负责人'},
        )
        self.assertEqual(canvas['tasks'][0]['id'], task.pk)
        self.assertEqual(canvas['tasks'][0]['status_label'], '待验收')
        self.assertEqual(canvas['tasks'][0]['assignee_name'], 'bob')
        self.assertEqual(canvas['tasks'][0]['parent_id'], None)
        self.assertEqual(canvas['tasks'][0]['start_date'], '2026-10-01')
        self.assertIn('<script id="canvas-data" type="application/json">', html)
        self.assertIn(f'/projects/{project.pk}/board/tasks/', html)

    def test_canvas_json_escapes_script_closing_tags(self) -> None:
        project = self.make_project()
        task = self.add_task(project, '</script><img src=x onerror=alert(1)>')
        task.description = '结束 </script> 标签'
        task.save()

        html = self.client.get(self.board_url(project)).content.decode('utf-8')

        self.assertNotIn('</script><img', html)
        self.assertIn('\\u003C/script\\u003E', html)
        self.assertIn('\\u003Cimg', html)

    def test_deep_task_tree_serializes_iteratively(self) -> None:
        project = self.make_project()
        parent = None
        for index in range(300):
            parent = TaskNode.objects.create(
                project=project, title=f'节点{index}', parent=parent,
                start_date='2026-10-01', end_date='2026-10-02',
            )

        page = self.client.get(self.board_url(project))

        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context['canvas_data']['tasks']), 300)

    def test_invalid_form_rerenders_input_with_status_400(self) -> None:
        project = self.make_project()

        response = self.client.post(
            f'{self.board_url(project)}tasks/',
            self.task_payload(title='保留我', start_date='2026-10-09', end_date='2026-10-01'),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('保留我', response.content.decode('utf-8'))
        self.assertTrue(response.context['task_form'].is_bound)


class ProjectCreationTests(BoardTestBase):
    def test_new_project_creates_owner_member_and_redirects_to_hub(self) -> None:
        response = self.client.post('/projects/new/', {'name': '新项目', 'description': '说明'})

        project = Project.objects.get(name='新项目')
        member = ProjectMember.objects.get(project=project)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'/projects/{project.pk}/space/')
        self.assertEqual(member.kind, ProjectMember.Kind.HUMAN)
        self.assertEqual(member.user, self.alice)
        self.assertEqual(member.name, 'alice')
        self.assertEqual(member.role, '项目负责人')

    def test_failed_member_creation_rolls_back_project(self) -> None:
        with mock.patch.object(
            ProjectMember.objects, 'create', side_effect=RuntimeError('boom')
        ), self.assertRaises(RuntimeError):
            self.client.post('/projects/new/', {'name': '回滚项目'})

        self.assertFalse(Project.objects.filter(name='回滚项目').exists())
