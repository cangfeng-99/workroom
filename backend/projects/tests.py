"""Project ownership, association and project-scoped workspace contracts (T012B)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from workspaces import grants


class ProjectFlowTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.other_root = self.base / 'other'
        self.other_root.mkdir()
        self.user = get_user_model().objects.create_user('alice')
        self.other = get_user_model().objects.create_user('bob')
        self.client = Client()
        self.client.force_login(self.user)

    # -- helpers -------------------------------------------------------
    def create_project(self, name: str = '项目一', path: str = '', owner=None):
        from projects.models import Project

        return Project.objects.create(
            owner=owner or self.user, name=name, workspace_path=path
        )

    def grant_workspace(self, path: Path, project=None) -> None:
        url = f'/workspace/?project={project.pk}' if project else '/workspace/'
        response = self.client.post(url, {'action': 'grant', 'path': str(path)})
        self.assertEqual(response.status_code, 302, response.content.decode('utf-8')[:300])

    def link(self, project, follow: bool = False):
        return self.client.post(
            f'/projects/{project.pk}/workspace/', {'workspace_path': 'D:/evil'}, follow=follow
        )

    # -- create/list/detail --------------------------------------------
    def test_anonymous_project_pages_redirect_to_login(self) -> None:
        project = self.create_project()
        anonymous = Client()
        for url in ('/projects/', '/projects/new/', f'/projects/{project.pk}/'):
            response = anonymous.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response['Location'].startswith('/accounts/login/?next='), url)

    def test_create_persists_owner_and_ignores_client_owner_and_path(self) -> None:
        from projects.models import Project

        response = self.client.post('/projects/new/', {
            'name': '我的项目',
            'description': '说明',
            'owner': str(self.other.pk),
            'workspace_path': 'D:/evil',
        })

        self.assertEqual(response.status_code, 302)
        project = Project.objects.get()
        self.assertEqual(project.owner, self.user)
        self.assertEqual(project.name, '我的项目')
        self.assertEqual(project.description, '说明')
        self.assertEqual(project.workspace_path, '')

    def test_create_linked_project_uses_server_grant_not_posted_path(self) -> None:
        from projects.models import Project

        self.grant_workspace(self.root)
        response = self.client.post('/projects/new/', {
            'name': '关联项目',
            'link_grant': 'on',
            'workspace_path': 'D:/evil',
        })

        self.assertEqual(response.status_code, 302)
        project = Project.objects.get()
        self.assertEqual(project.workspace_path, str(self.root))
        self.assertEqual(self.client.session[grants.SESSION_KEY]['project_id'], '')
        self.assertEqual(self.client.session[grants.SESSION_KEY]['root'], str(self.root))
        self.assertTrue(Project.objects.filter(owner=self.user).exists())

    def test_create_linked_without_grant_is_rejected(self) -> None:
        from projects.models import Project

        response = self.client.post('/projects/new/', {'name': '无授权', 'link_grant': 'on'})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.exists())
        self.assertIn('未授权', response.content.decode('utf-8'))

    def test_list_only_shows_own_projects_and_is_no_store(self) -> None:
        mine = self.create_project('我的')
        self.create_project('别人的', owner=self.other)

        response = self.client.get('/projects/')
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('我的', html)
        self.assertNotIn('别人的', html)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertContains(self.client.get(f'/projects/{mine.pk}/'), '我的')

    def test_detail_and_posts_are_owner_scoped(self) -> None:
        foreign = self.create_project('别人的', owner=self.other)

        self.assertEqual(self.client.get(f'/projects/{foreign.pk}/').status_code, 404)
        self.assertEqual(self.link(foreign).status_code, 404)
        self.assertEqual(self.client.get(f'/projects/{foreign.pk}/open/').status_code, 404)
        self.assertEqual(self.client.get('/projects/9999/').status_code, 404)

    def test_project_posts_require_csrf(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        project = self.create_project()

        self.assertEqual(csrf_client.post('/projects/new/', {'name': 'x'}).status_code, 403)
        self.assertEqual(csrf_client.post(f'/projects/{project.pk}/workspace/', {}).status_code, 403)

    # -- association ----------------------------------------------------
    def test_link_requires_grant_and_existing_folder(self) -> None:
        project = self.create_project()

        response = self.link(project)
        self.assertEqual(response.status_code, 400)

        session = self.client.session
        session[grants.SESSION_KEY] = {
            'root': str(self.base / 'missing'), 'grant_id': 'g', 'user_id': str(self.user.pk),
        }
        session.save()
        response = self.link(project)

        self.assertEqual(response.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, '')

    def test_link_persists_path_and_rotates_grant_to_project(self) -> None:
        project = self.create_project()
        self.grant_workspace(self.root)
        old_grant_id = self.client.session[grants.SESSION_KEY]['grant_id']

        response = self.link(project)

        self.assertRedirects(response, f'/projects/{project.pk}/', fetch_redirect_response=False)
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, str(self.root))
        data = self.client.session[grants.SESSION_KEY]
        self.assertEqual(data['project_id'], str(project.pk))
        self.assertEqual(data['root'], str(self.root))
        self.assertNotEqual(data['grant_id'], old_grant_id)

    def test_link_does_not_grant_files_by_itself(self) -> None:
        project = self.create_project()
        self.grant_workspace(self.root)
        self.link(project)
        session = self.client.session
        session[grants.SESSION_KEY] = {}
        session.save()

        page = self.client.get(f'/workspace/?project={project.pk}')
        denied = self.client.post(
            f'/workspace/?project={project.pk}', {'action': 'create', 'name': 'x.txt', 'content': 'x'}
        )

        self.assertIn('未授权', page.content.decode('utf-8'))
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'x.txt').exists())

    # -- open -----------------------------------------------------------
    def test_open_without_workspace_redirects_to_detail(self) -> None:
        project = self.create_project()

        response = self.client.get(f'/projects/{project.pk}/open/', follow=True)

        self.assertRedirects(response, f'/projects/{project.pk}/')
        self.assertIn('尚未关联', response.content.decode('utf-8'))

    def test_open_redirects_to_project_workspace(self) -> None:
        project = self.create_project(path=str(self.root))

        response = self.client.get(f'/projects/{project.pk}/open/')

        self.assertRedirects(
            response, f'/workspace/?project={project.pk}', fetch_redirect_response=False
        )

    # -- project workspace ---------------------------------------------
    def test_workspace_rejects_invalid_or_foreign_project_query(self) -> None:
        foreign = self.create_project(owner=self.other)
        for query in ('abc', '0', '-1', '1.5', '9999', str(foreign.pk), ''):
            response = self.client.get(f'/workspace/?project={query}')
            self.assertEqual(response.status_code, 404, query)
        self.assertNotIn(grants.SESSION_KEY, self.client.session)

    def test_unusual_project_ids_return_404_before_file_access(self) -> None:
        with mock.patch('workspaces.views.Workspace') as filesystem:
            for query in ('²', '9' * 5000, '9' * 30):
                response = self.client.get('/workspace/', {'project': query})
                self.assertEqual(response.status_code, 404)
            filesystem.assert_not_called()

    def test_old_project_page_cannot_write_after_switching_projects(self) -> None:
        first = self.create_project(path=str(self.root))
        second = self.create_project('第二个', path=str(self.other_root))
        (self.root / 'same.txt').write_text('first', encoding='utf-8')
        (self.other_root / 'same.txt').write_text('second', encoding='utf-8')
        self.grant_workspace(self.root, first)
        old_id = self.client.session[grants.SESSION_KEY]['grant_id']
        page = self.client.get(f'/workspace/?project={first.pk}&file=same.txt')
        revision = page.context['save_form']['revision'].value()
        self.grant_workspace(self.other_root, second)

        denied = self.client.post(f'/workspace/?project={first.pk}', {
            'action': 'save', 'grant_id': old_id, 'path': 'same.txt',
            'revision': revision, 'content': 'wrong project write',
        })

        self.assertEqual(denied.status_code, 403)
        self.assertEqual((self.root / 'same.txt').read_text(encoding='utf-8'), 'first')
        self.assertEqual((self.other_root / 'same.txt').read_text(encoding='utf-8'), 'second')

    def test_changed_project_location_invalidates_old_folder_grant(self) -> None:
        project = self.create_project(path=str(self.root))
        self.grant_workspace(self.root, project)
        old_id = self.client.session[grants.SESSION_KEY]['grant_id']
        project.workspace_path = str(self.other_root)
        project.save(update_fields=['workspace_path'])

        page = self.client.get(f'/workspace/?project={project.pk}')
        denied = self.client.post(f'/workspace/?project={project.pk}', {
            'action': 'create', 'grant_id': old_id, 'name': 'blocked.txt', 'content': 'x',
        })

        self.assertContains(page, '未授权')
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'blocked.txt').exists())
        self.assertFalse((self.other_root / 'blocked.txt').exists())

    def test_project_workspace_requires_authorization_and_prefills_associated_root(self) -> None:
        project = self.create_project('展示项目', path=str(self.root))

        response = self.client.get(f'/workspace/?project={project.pk}')
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('未授权', html)
        self.assertIn('展示项目', html)
        self.assertIn(f'/projects/{project.pk}/', html)
        self.assertEqual(response.context['grant_path'], str(self.root))

    def test_project_grant_requires_matching_associated_root(self) -> None:
        project = self.create_project(path=str(self.root))

        denied = self.client.post(
            f'/workspace/?project={project.pk}', {'action': 'grant', 'path': str(self.other_root)}
        )

        self.assertEqual(denied.status_code, 400)
        self.assertNotIn(grants.SESSION_KEY, self.client.session)

        response = self.client.post(
            f'/workspace/?project={project.pk}', {'action': 'grant', 'path': str(self.root)}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[grants.SESSION_KEY]['project_id'], str(project.pk))

    def test_grant_is_isolated_between_project_and_independent_workspace(self) -> None:
        project = self.create_project(path=str(self.root))
        self.grant_workspace(self.root, project)

        other_project = self.create_project('另一个', path=str(self.other_root))
        other_page = self.client.get(f'/workspace/?project={other_project.pk}')
        independent = self.client.get('/workspace/')

        self.assertIn('未授权', other_page.content.decode('utf-8'))
        self.assertIn('未授权', independent.content.decode('utf-8'))
        self.assertEqual(
            self.client.session[grants.SESSION_KEY]['project_id'], str(project.pk)
        )

    def test_project_save_and_create_redirects_keep_project_context(self) -> None:
        project = self.create_project(path=str(self.root))
        self.grant_workspace(self.root, project)
        grant_id = self.client.session[grants.SESSION_KEY]['grant_id']

        created = self.client.post(f'/workspace/?project={project.pk}', {
            'action': 'create', 'grant_id': grant_id, 'name': 'a.txt', 'content': 'one',
        })

        self.assertEqual(created.status_code, 302)
        self.assertIn(f'project={project.pk}', created['Location'])
        page = self.client.get(f'/workspace/?project={project.pk}&file=a.txt')
        revision = page.context['save_form']['revision'].value()
        saved = self.client.post(f'/workspace/?project={project.pk}', {
            'action': 'save', 'grant_id': grant_id, 'path': 'a.txt',
            'revision': revision, 'content': 'two',
        })

        self.assertEqual(saved.status_code, 302)
        self.assertEqual(
            parse_qs(urlparse(saved['Location']).query)['project'], [str(project.pk)]
        )
        self.assertEqual((self.root / 'a.txt').read_text(encoding='utf-8'), 'two')

    def test_project_revoke_redirect_keeps_project_context(self) -> None:
        project = self.create_project(path=str(self.root))
        self.grant_workspace(self.root, project)

        response = self.client.post(f'/workspace/?project={project.pk}', {'action': 'revoke'})

        self.assertRedirects(
            response, f'/workspace/?project={project.pk}', fetch_redirect_response=False
        )
        self.assertNotIn(grants.SESSION_KEY, self.client.session)

    # -- T013: authorization vs association status ----------------------
    def test_list_shows_current_grant_and_offers_explicit_link(self) -> None:
        project = self.create_project('未关联项目')
        self.grant_workspace(self.root)
        grant_id = self.client.session[grants.SESSION_KEY]['grant_id']

        html = self.client.get('/projects/').content.decode('utf-8')

        self.assertIn(str(self.root), html)
        self.assertIn('独立工作区', html)
        self.assertIn('尚未授权', html)
        self.assertIn(f'/projects/{project.pk}/workspace/', html)
        self.assertIn('关联到此项目', html)
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, '')
        self.assertEqual(self.client.session[grants.SESSION_KEY]['project_id'], '')
        self.assertEqual(self.client.session[grants.SESSION_KEY]['grant_id'], grant_id)

    def test_explicit_link_from_grant_makes_project_authorized_everywhere(self) -> None:
        project = self.create_project('待关联项目')
        self.grant_workspace(self.root)

        response = self.client.post(f'/projects/{project.pk}/workspace/', follow=True)

        self.assertRedirects(response, f'/projects/{project.pk}/')
        self.assertContains(response, '已授权，可读写')
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, str(self.root))
        self.assertContains(self.client.get('/projects/'), '已授权，可读写')
        page = self.client.get(f'/workspace/?project={project.pk}')
        self.assertContains(page, '已授权')
        self.assertTrue(page.context['granted'])

    def test_standalone_grant_does_not_authorize_same_path_project(self) -> None:
        project = self.create_project('同路径项目', path=str(self.root))
        self.grant_workspace(self.root)
        grant_id = self.client.session[grants.SESSION_KEY]['grant_id']

        detail = self.client.get(f'/projects/{project.pk}/')
        listing = self.client.get('/projects/')

        self.assertNotContains(detail, '已授权，可读写')
        self.assertContains(detail, '尚未授权')
        self.assertNotContains(listing, '已授权，可读写')
        self.assertContains(listing, '尚未授权')
        self.assertEqual(self.client.session[grants.SESSION_KEY]['grant_id'], grant_id)
        self.assertEqual(self.client.session[grants.SESSION_KEY]['project_id'], '')
        project.refresh_from_db()
        self.assertEqual(project.workspace_path, str(self.root))

    def test_detail_and_list_only_mark_matching_project_grant_authorized(self) -> None:
        project = self.create_project('甲项目', path=str(self.root))
        other = self.create_project('乙项目', path=str(self.other_root))
        self.grant_workspace(self.root, project)

        self.assertContains(self.client.get(f'/projects/{project.pk}/'), '已授权，可读写')
        listing = self.client.get('/projects/')
        self.assertContains(listing, '已授权，可读写')
        self.assertContains(listing, '此授权属于项目')
        self.assertNotContains(listing, '此授权用于独立工作区')
        other_detail = self.client.get(f'/projects/{other.pk}/')
        self.assertNotContains(other_detail, '已授权，可读写')
        self.assertContains(other_detail, '尚未授权')

        project.workspace_path = str(self.other_root)
        project.save(update_fields=['workspace_path'])
        changed = self.client.get(f'/projects/{project.pk}/')
        self.assertNotContains(changed, '已授权，可读写')
        self.assertContains(changed, '尚未授权')
        changed_list = self.client.get('/projects/')
        self.assertNotContains(changed_list, '已授权，可读写')
        self.assertContains(changed_list, '已不再生效')

    def test_unavailable_grant_project_is_not_presented_as_usable(self) -> None:
        project = self.create_project(path=str(self.root))
        self.grant_workspace(self.root, project)
        project.delete()

        listing = self.client.get('/projects/')

        self.assertContains(listing, '授权对应的项目已不可用')
        self.assertNotContains(listing, '此授权用于独立工作区')
        self.assertNotContains(listing, '已授权，可读写')

    def test_malformed_project_in_old_grant_does_not_break_status_pages(self) -> None:
        self.grant_workspace(self.root)
        for project_id in ('9' * 5000, '²', '-1'):
            with self.subTest(project_id_length=len(project_id)):
                session = self.client.session
                session[grants.SESSION_KEY]['project_id'] = project_id
                session.save()
                self.assertEqual(self.client.get('/projects/').status_code, 200)
                page = self.client.get('/workspace/')
                self.assertEqual(page.status_code, 200)
                self.assertFalse(page.context['granted'])

    def test_independent_workspace_explains_project_grant_and_stays_unauthorized(self) -> None:
        project = self.create_project('项目上下文', path=str(self.root))
        self.grant_workspace(self.root, project)
        grant_id = self.client.session[grants.SESSION_KEY]['grant_id']

        page = self.client.get('/workspace/')
        html = page.content.decode('utf-8')

        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context['granted'])
        self.assertIn('独立工作区', html)
        self.assertIn('项目上下文', html)
        self.assertIn(f'/projects/{project.pk}/', html)
        self.assertEqual(self.client.session[grants.SESSION_KEY]['grant_id'], grant_id)
        denied = self.client.post('/workspace/', {'action': 'create', 'name': 'x.txt', 'content': 'x'})
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'x.txt').exists())

    def test_independent_authorized_page_says_not_linked_to_projects(self) -> None:
        self.grant_workspace(self.root)

        page = self.client.get('/workspace/')
        html = page.content.decode('utf-8')

        self.assertTrue(page.context['granted'])
        self.assertIn('独立工作区', html)
        self.assertIn('不会自动关联', html)

    def test_project_workspace_explains_standalone_grant_is_not_linked(self) -> None:
        project = self.create_project(path=str(self.root))
        self.grant_workspace(self.root)

        page = self.client.get(f'/workspace/?project={project.pk}')
        html = page.content.decode('utf-8')

        self.assertFalse(page.context['granted'])
        self.assertIn('独立工作区', html)
        self.assertIn('尚未关联到本项目', html)

    def test_relogin_keeps_project_but_requires_new_authorization(self) -> None:
        self.user.set_password('Str0ng-Pass!234')
        self.user.save(update_fields=['password'])
        self.client.force_login(self.user)
        project = self.create_project(path=str(self.root))
        self.grant_workspace(self.root, project)

        self.client.logout()
        response = self.client.post('/accounts/login/', {
            'username': 'alice', 'password': 'Str0ng-Pass!234',
        })
        self.assertRedirects(response, '/projects/', fetch_redirect_response=False)
        self.assertNotIn(grants.SESSION_KEY, self.client.session)

        page = self.client.get(f'/workspace/?project={project.pk}')
        self.assertIn('未授权', page.content.decode('utf-8'))
        self.assertEqual(self.client.get(f'/projects/{project.pk}/').status_code, 200)
