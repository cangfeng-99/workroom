"""HTTP contract tests for the demo workspace page (real disk, temp root)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import Client, TestCase, override_settings

from workspaces.services import WELCOME_NAME


class WorkspacePageTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'demo'
        self.override = override_settings(WORKSPACE_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client = Client()

    def grant(self) -> None:
        response = self.client.post('/workspace/', {'action': 'grant'})
        self.assertEqual(response.status_code, 302)

    def test_get_before_grant_does_not_touch_demo_disk(self) -> None:
        response = self.client.get('/workspace/')

        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('未授权', body)
        self.assertNotIn('welcome.md', body)
        self.assertFalse(self.root.exists())
        self.assertIn('no-store', response['Cache-Control'])

    def test_grant_is_per_browser_and_creates_demo_once(self) -> None:
        self.grant()
        other = Client()

        response = self.client.get('/workspace/')
        self.assertIn('已授权', response.content.decode('utf-8'))
        self.assertIn(WELCOME_NAME, response.content.decode('utf-8'))

        other_response = other.get('/workspace/')
        self.assertEqual(other_response.status_code, 200)
        self.assertIn('未授权', other_response.content.decode('utf-8'))
        denied = other.post('/workspace/', {'action': 'create', 'name': 'other.txt', 'content': 'x'})
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'other.txt').exists())

    def test_grant_then_create_then_read_keeps_original_text(self) -> None:
        self.grant()
        content = '  第一行\n第二行  \n\n'

        response = self.client.post(
            '/workspace/',
            {'action': 'create', 'name': 'note.txt', 'content': content},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual((self.root / 'note.txt').read_text(encoding='utf-8'), content)
        page = self.client.get('/workspace/', {'file': 'note.txt'})
        self.assertEqual(page.status_code, 200)
        self.assertIn(content, page.content.decode('utf-8'))

    def test_create_never_overwrites_existing_file(self) -> None:
        self.grant()
        target = self.root / 'taken.txt'
        target.write_text('original', encoding='utf-8')

        response = self.client.post(
            '/workspace/',
            {'action': 'create', 'name': 'taken.txt', 'content': 'replacement'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('已存在', response.content.decode('utf-8'))
        self.assertEqual(target.read_text(encoding='utf-8'), 'original')

    def test_create_rejects_trailing_whitespace_without_renaming(self) -> None:
        self.grant()
        response = self.client.post(
            '/workspace/', {'action': 'create', 'name': 'renamed.txt ', 'content': 'payload'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.root / 'renamed.txt').exists())

    def test_create_redirect_shows_success_once(self) -> None:
        self.grant()
        response = self.client.post(
            '/workspace/', {'action': 'create', 'name': 'created.md', 'content': 'hello'},
            follow=True,
        )
        self.assertContains(response, '已创建：created.md')
        self.assertNotContains(self.client.get('/workspace/'), '已创建：created.md')

    def test_revoke_blocks_file_operations(self) -> None:
        self.grant()

        response = self.client.post('/workspace/', {'action': 'revoke'})

        self.assertEqual(response.status_code, 302)
        self.assertIn('未授权', self.client.get('/workspace/').content.decode('utf-8'))
        denied = self.client.post(
            '/workspace/',
            {'action': 'create', 'name': 'after.txt', 'content': 'x'},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'after.txt').exists())

    def test_post_without_csrf_token_is_rejected(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post('/workspace/', {'action': 'grant'})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.root.exists())

    def test_path_traversal_is_rejected_and_outside_sentinel_untouched(self) -> None:
        self.grant()
        sentinel = Path(self.tmp.name) / 'outside' / 'sentinel.txt'
        sentinel.parent.mkdir()
        sentinel.write_text('DO-NOT-TOUCH', encoding='utf-8')

        response = self.client.post(
            '/workspace/',
            {'action': 'create', 'name': '../sentinel.txt', 'content': 'pwned'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'DO-NOT-TOUCH')
        self.assertFalse((Path(self.tmp.name) / 'sentinel.txt').exists())

    def test_file_content_is_html_escaped(self) -> None:
        self.grant()
        self.client.post(
            '/workspace/',
            {'action': 'create', 'name': 'escape.txt', 'content': '<script>alert(1)</script>'},
        )

        body = self.client.get('/workspace/', {'file': 'escape.txt'}).content.decode('utf-8')

        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertNotIn('<script>alert(1)</script>', body)

    def test_unknown_action_is_rejected(self) -> None:
        self.grant()

        response = self.client.post('/workspace/', {'action': 'delete', 'name': WELCOME_NAME})

        self.assertEqual(response.status_code, 400)
        self.assertTrue((self.root / WELCOME_NAME).exists())

    def test_grant_is_invalid_after_server_root_changes(self) -> None:
        self.grant()
        new_root = Path(self.tmp.name) / 'other-demo'

        with override_settings(WORKSPACE_ROOT=new_root):
            body = self.client.get('/workspace/').content.decode('utf-8')

        self.assertIn('未授权', body)
        self.assertFalse(new_root.exists())
