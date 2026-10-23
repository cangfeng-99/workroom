"""HTTP contract tests for the real-folder workspace page (temp disk roots)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest import mock

from django.test import Client, TestCase

from workspaces import views as workspace_views
from workspaces.picker import PickerError


class WorkspacePageTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.client = Client()

    # -- helpers -------------------------------------------------------
    def grant(self, path: Path | str | None = None) -> None:
        target = str(path if path is not None else self.root)
        response = self.client.post('/workspace/', {'action': 'grant', 'path': target})
        self.assertEqual(response.status_code, 302, response.content.decode('utf-8')[:400])

    def grant_id(self) -> str:
        return self.client.session[workspace_views.SESSION_KEY]['grant_id']

    def snapshot(self) -> set[str]:
        return {str(item.relative_to(self.base)) for item in self.base.rglob('*')}

    # -- authorization -------------------------------------------------
    def test_get_before_grant_writes_nothing_and_shows_full_path_field(self) -> None:
        before = self.snapshot()
        response = self.client.get('/workspace/')

        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('未授权', body)
        self.assertIn('name="path"', body)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.snapshot(), before)

    def test_get_never_opens_native_dialog(self) -> None:
        with mock.patch.object(
            workspace_views, 'pick_folder', side_effect=AssertionError('dialog opened on GET')
        ):
            response = self.client.get('/workspace/')
        self.assertEqual(response.status_code, 200)

    def test_grant_existing_folder_creates_no_files_and_shows_full_path(self) -> None:
        (self.root / 'notes.txt').write_text('hello', encoding='utf-8')
        before = self.snapshot()

        self.grant()

        body = self.client.get('/workspace/').content.decode('utf-8')
        self.assertIn('已授权', body)
        self.assertIn(str(self.root), body)
        self.assertIn('notes.txt', body)
        self.assertFalse((self.root / 'welcome.md').exists())
        self.assertEqual(self.snapshot(), before)

    def test_grant_rejects_missing_relative_and_unc_paths(self) -> None:
        missing = self.base / 'does-not-exist'

        for path in (str(missing), 'relative/folder', '\\\\server\\share'):
            response = self.client.post('/workspace/', {'action': 'grant', 'path': path})
            self.assertEqual(response.status_code, 400, path)
            self.assertNotIn(workspace_views.SESSION_KEY, self.client.session)

        self.assertFalse(missing.exists())

    def test_legacy_demo_session_key_does_not_grant(self) -> None:
        session = self.client.session
        session[workspace_views.LEGACY_SESSION_KEY] = str(self.root)
        session.save()

        body = self.client.get('/workspace/').content.decode('utf-8')
        denied = self.client.post('/workspace/', {'action': 'create', 'name': 'x.txt', 'content': 'x'})

        self.assertIn('未授权', body)
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'x.txt').exists())

    def test_other_browser_has_no_grant(self) -> None:
        self.grant()
        other = Client()

        self.assertIn('未授权', other.get('/workspace/').content.decode('utf-8'))
        denied = other.post(
            '/workspace/',
            {'action': 'create', 'grant_id': self.grant_id(), 'name': 'other.txt', 'content': 'x'},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'other.txt').exists())

    def test_revoke_blocks_reads_and_writes(self) -> None:
        (self.root / 'keep.txt').write_text('keep', encoding='utf-8')
        self.grant()
        grant_id = self.grant_id()

        response = self.client.post('/workspace/', {'action': 'revoke'})

        self.assertEqual(response.status_code, 302)
        self.assertIn('未授权', self.client.get('/workspace/').content.decode('utf-8'))
        denied = self.client.post(
            '/workspace/',
            {'action': 'create', 'grant_id': grant_id, 'name': 'after.txt', 'content': 'x'},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse((self.root / 'after.txt').exists())

    # -- browsing ------------------------------------------------------
    def test_subdirectory_browsing_and_listing_limits_text(self) -> None:
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'app.py').write_text('print(1)\n', encoding='utf-8')

        self.grant()
        body = self.client.get('/workspace/', {'dir': 'src'}).content.decode('utf-8')

        self.assertIn('app.py', body)
        self.assertIn('返回上级', body)
        self.assertIn('100', body)

    def test_traversal_outside_root_is_rejected(self) -> None:
        sentinel = self.base / 'sentinel.txt'
        sentinel.write_text('DO-NOT-TOUCH', encoding='utf-8')
        self.grant()

        page = self.client.get('/workspace/', {'file': '../sentinel.txt'})
        created = self.client.post(
            '/workspace/',
            {
                'action': 'create',
                'grant_id': self.grant_id(),
                'directory': '..',
                'name': 'sentinel.txt',
                'content': 'pwned',
            },
        )

        self.assertEqual(page.status_code, 200)
        self.assertIn('路径或文件名无效', page.content.decode('utf-8'))
        self.assertEqual(created.status_code, 400)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'DO-NOT-TOUCH')

    # -- editing -------------------------------------------------------
    def test_read_file_into_editable_form(self) -> None:
        content = '\n第一行\n第二行  \n'
        (self.root / 'note.txt').write_text(content, encoding='utf-8')
        self.grant()

        body = self.client.get('/workspace/', {'file': 'note.txt'}).content.decode('utf-8')

        self.assertIn('正在编辑', body)
        self.assertIn('保存到原文件', body)
        self.assertIn('name="revision"', body)
        self.assertIn('第一行', body)

    def test_save_writes_back_in_place_with_first_line_newline(self) -> None:
        target = self.root / 'note.txt'
        target.write_text('old\n', encoding='utf-8')
        self.grant()
        page = self.client.get('/workspace/', {'file': 'note.txt'}).content.decode('utf-8')
        revision = page.split('name="revision" value="', 1)[1].split('"', 1)[0]
        new_content = '\n新的第一行\n第二行\n'

        response = self.client.post(
            '/workspace/',
            {
                'action': 'save',
                'grant_id': self.grant_id(),
                'path': 'note.txt',
                'revision': revision,
                'content': new_content,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(target.read_text(encoding='utf-8'), new_content)

    def test_save_in_subdirectory_writes_original_file(self) -> None:
        (self.root / 'src').mkdir()
        target = self.root / 'src' / 'app.py'
        target.write_text('a = 1\n', encoding='utf-8')
        self.grant()
        page = self.client.get('/workspace/', {'dir': 'src', 'file': 'src/app.py'}).content
        revision = page.decode('utf-8').split('name="revision" value="', 1)[1].split('"', 1)[0]

        response = self.client.post(
            '/workspace/',
            {
                'action': 'save',
                'grant_id': self.grant_id(),
                'path': 'src/app.py',
                'revision': revision,
                'content': 'a = 2\n',
                'directory': 'src',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(target.read_text(encoding='utf-8'), 'a = 2\n')

    def test_external_change_conflict_keeps_user_input_and_original_file(self) -> None:
        target = self.root / 'note.txt'
        target.write_text('original\n', encoding='utf-8')
        self.grant()
        page = self.client.get('/workspace/', {'file': 'note.txt'}).content.decode('utf-8')
        revision = page.split('name="revision" value="', 1)[1].split('"', 1)[0]
        target.write_text('changed outside\n', encoding='utf-8')

        response = self.client.post(
            '/workspace/',
            {
                'action': 'save',
                'grant_id': self.grant_id(),
                'path': 'note.txt',
                'revision': revision,
                'content': '我的编辑不会丢',
            },
        )

        self.assertEqual(response.status_code, 400)
        body = response.content.decode('utf-8')
        self.assertIn('已被外部修改', body)
        self.assertIn('我的编辑不会丢', body)
        self.assertEqual(target.read_text(encoding='utf-8'), 'changed outside\n')

    def test_new_file_never_overwrites_existing(self) -> None:
        target = self.root / 'taken.txt'
        target.write_text('original', encoding='utf-8')
        self.grant()

        response = self.client.post(
            '/workspace/',
            {
                'action': 'create',
                'grant_id': self.grant_id(),
                'name': 'taken.txt',
                'content': 'replacement',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('不会覆盖', response.content.decode('utf-8'))
        self.assertEqual(target.read_text(encoding='utf-8'), 'original')

    def test_create_requires_matching_grant_id(self) -> None:
        self.grant()
        response = self.client.post(
            '/workspace/', {'action': 'create', 'grant_id': 'stale', 'name': 'x.txt', 'content': 'x'}
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.root / 'x.txt').exists())

    def test_switching_root_rejects_old_page_grant(self) -> None:
        first = self.root
        second = self.base / 'second'
        second.mkdir()
        (first / 'note.txt').write_text('first root\n', encoding='utf-8')
        self.grant(first)
        page = self.client.get('/workspace/', {'file': 'note.txt'}).content.decode('utf-8')
        revision = page.split('name="revision" value="', 1)[1].split('"', 1)[0]
        old_grant = self.grant_id()

        self.grant(second)
        response = self.client.post(
            '/workspace/',
            {
                'action': 'create',
                'grant_id': old_grant,
                'name': 'leak.txt',
                'content': 'should not land here',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('授权已变更', response.content.decode('utf-8'))
        self.assertFalse((second / 'leak.txt').exists())

        old_save = self.client.post(
            '/workspace/',
            {
                'action': 'save',
                'grant_id': old_grant,
                'path': 'note.txt',
                'revision': revision,
                'content': 'leaked write',
            },
        )
        self.assertEqual(old_save.status_code, 403)
        self.assertFalse((second / 'note.txt').exists())
        self.assertEqual((first / 'note.txt').read_text(encoding='utf-8'), 'first root\n')
        self.assertTrue(revision)

    def test_create_then_read_then_save_roundtrip(self) -> None:
        self.grant()
        content = '  第一行\n第二行  \n\n'

        created = self.client.post(
            '/workspace/',
            {'action': 'create', 'grant_id': self.grant_id(), 'name': 'note.txt', 'content': content},
        )

        self.assertEqual(created.status_code, 302)
        self.assertEqual((self.root / 'note.txt').read_text(encoding='utf-8'), content)
        self.assertIn(content, self.client.get('/workspace/', {'file': 'note.txt'}).content.decode('utf-8'))

    def test_trailing_space_name_is_rejected_without_renaming(self) -> None:
        self.grant()
        response = self.client.post(
            '/workspace/',
            {'action': 'create', 'grant_id': self.grant_id(), 'name': 'renamed.txt ', 'content': 'x'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.root / 'renamed.txt').exists())

    def test_binary_nul_file_is_rejected_and_unchanged(self) -> None:
        target = self.root / 'blob.py'
        target.write_bytes(b'line1\x00line2')
        self.grant()

        page = self.client.get('/workspace/', {'file': 'blob.py'})

        self.assertEqual(page.status_code, 200)
        self.assertIn('二进制', page.content.decode('utf-8'))
        self.assertEqual(target.read_bytes(), b'line1\x00line2')

    def test_file_content_is_html_escaped(self) -> None:
        (self.root / 'escape.txt').write_text('<script>alert(1)</script>', encoding='utf-8')
        self.grant()

        body = self.client.get('/workspace/', {'file': 'escape.txt'}).content.decode('utf-8')

        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertNotIn('<script>alert(1)</script>', body)

    # -- security ------------------------------------------------------
    def test_post_without_csrf_token_is_rejected(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post('/workspace/', {'action': 'grant', 'path': str(self.root)})

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(workspace_views.SESSION_KEY, csrf_client.session)

    def test_unknown_action_is_rejected(self) -> None:
        self.grant()
        (self.root / 'keep.txt').write_text('keep', encoding='utf-8')

        response = self.client.post(
            '/workspace/', {'action': 'delete', 'grant_id': self.grant_id(), 'name': 'keep.txt'}
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue((self.root / 'keep.txt').exists())

    # -- native picker -------------------------------------------------
    def test_pick_only_fills_path_and_does_not_grant(self) -> None:
        chosen = str(self.root)
        with mock.patch.object(workspace_views, 'pick_folder', return_value=chosen):
            response = self.client.post('/workspace/', {'action': 'pick'})

        body = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('已选择路径', body)
        self.assertIn(chosen, body)
        self.assertIn('未授权', body)
        self.assertNotIn(workspace_views.SESSION_KEY, self.client.session)

    def test_pick_cancel_keeps_existing_grant(self) -> None:
        (self.root / 'keep.md').write_text('keep', encoding='utf-8')
        self.grant()
        with mock.patch.object(
            workspace_views, 'pick_folder', side_effect=PickerError('picker_cancelled')
        ):
            response = self.client.post('/workspace/', {'action': 'pick'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('已取消选择', response.content.decode('utf-8'))
        self.assertIn(workspace_views.SESSION_KEY, self.client.session)
        self.assertIn('keep.md', response.content.decode('utf-8'))

    def test_pick_failure_keeps_manual_path_input_available(self) -> None:
        for code in ('picker_timeout', 'picker_unavailable', 'picker_failed'):
            with mock.patch.object(
                workspace_views, 'pick_folder', side_effect=PickerError(code)
            ):
                response = self.client.post('/workspace/', {'action': 'pick'})
            body = response.content.decode('utf-8')
            self.assertEqual(response.status_code, 400)
            self.assertIn('手工输入', body)
            self.assertIn('name="path"', body)

    def test_save_keeps_leading_space_in_filename_and_never_edits_its_neighbor(self) -> None:
        target = self.root / ' note.md'
        neighbor = self.root / 'note.md'
        target.write_text('same', encoding='utf-8')
        neighbor.write_text('same', encoding='utf-8')
        self.grant()
        page = self.client.get('/workspace/', {'file': target.name})
        revision = page.context['save_form']['revision'].value()

        response = self.client.post('/workspace/', {
            'action': 'save', 'grant_id': self.grant_id(), 'path': target.name,
            'revision': revision, 'content': 'edited',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(target.read_text(encoding='utf-8'), 'edited')
        self.assertEqual(neighbor.read_text(encoding='utf-8'), 'same')

    def test_create_keeps_leading_space_in_directory(self) -> None:
        (self.root / ' src').mkdir()
        (self.root / 'src').mkdir()
        self.grant()

        response = self.client.post('/workspace/', {
            'action': 'create', 'grant_id': self.grant_id(), 'directory': ' src',
            'name': 'app.py', 'content': 'print(1)',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue((self.root / ' src' / 'app.py').exists())
        self.assertFalse((self.root / 'src' / 'app.py').exists())

    def test_editor_and_create_forms_have_unique_ids_and_distinct_labels(self) -> None:
        (self.root / 'note.md').write_text('text', encoding='utf-8')
        self.grant()
        body = self.client.get('/workspace/', {'file': 'note.md'}).content.decode('utf-8')

        ids = re.findall(r' id="([^"]+)"', body)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('编辑内容', body)
        self.assertIn('新文件内容', body)

    def test_save_redirect_preserves_special_characters_in_paths(self) -> None:
        folder = self.root / 'src & 文档#1'
        folder.mkdir()
        target = folder / 'a+b&c#1.md'
        target.write_text('old', encoding='utf-8')
        self.grant()
        relative = target.relative_to(self.root).as_posix()
        page = self.client.get('/workspace/', {'dir': folder.name, 'file': relative})

        response = self.client.post('/workspace/', {
            'action': 'save', 'grant_id': self.grant_id(), 'path': relative,
            'revision': page.context['save_form']['revision'].value(), 'content': 'new',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['save_form']['path'].value(), relative)
        self.assertEqual(target.read_text(encoding='utf-8'), 'new')

    def test_picked_replacement_folder_exposes_authorize_button(self) -> None:
        self.grant()
        with mock.patch.object(workspace_views, 'pick_folder', return_value=str(self.root)):
            response = self.client.post('/workspace/', {'action': 'pick'})

        self.assertContains(response, '<details open>')
