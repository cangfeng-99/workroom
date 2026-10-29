import json
import tempfile
import tomllib
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from apps.projects.models import Member, Project, ProjectMembership, ToolToken


@override_settings(WORKROOM_MODE='server', WORKROOM_LOCAL_PREVIEW=True, ALLOWED_HOSTS=['127.0.0.1', 'testserver'])
class QuickConnectionTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.codex').mkdir()
        self.override = override_settings(MCP_HOME=self.home)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.owner = User.objects.create_user('quick-owner')
        self.viewer = User.objects.create_user('quick-viewer')
        self.project = Project.objects.create(name='Quick', goal_title='Ship')
        ProjectMembership.objects.create(project=self.project, user=self.owner, role='owner')
        ProjectMembership.objects.create(project=self.project, user=self.viewer, role='viewer')
        self.client.force_login(self.owner)
        self.url = f'/p/{self.project.pk}/connections/quick/codex/'

    def connect(self, **data):
        return self.client.post(self.url, {'mode': 'local', 'scope': 'execute', **data}, HTTP_HOST='127.0.0.1:8011', HTTP_ACCEPT='application/json')

    def test_click_installs_scoped_config_without_clobbering_existing_connection(self):
        path = self.home / '.codex/config.toml'
        path.write_text('[mcp_servers.workroom]\ncommand="old"\n')
        response = self.connect()
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(connection_user=self.owner)
        parsed = tomllib.loads(path.read_text())['mcp_servers']
        name = f'workroom-p{self.project.pk}-{member.connection_id.hex[:8]}'
        self.assertEqual(parsed['workroom']['command'], 'old')
        self.assertEqual(parsed[name]['url'], 'http://127.0.0.1:8011/mcp/')
        self.assertEqual(ToolToken.objects.get().member_id, member.pk)
        self.assertIsNone(member.last_connected_at)
        self.assertNotIn('Bearer', response.content.decode())
        self.assertEqual(response.json()['state'], 'configured')
        self.assertEqual(self.connect().status_code, 200)
        self.assertEqual(Member.objects.filter(connection_user=self.owner).count(), 1)
        self.assertEqual(ToolToken.objects.filter(revoked_at__isnull=True).count(), 1)

    def test_server_and_remote_requests_cannot_write_host_configuration(self):
        with override_settings(WORKROOM_LOCAL_PREVIEW=False):
            self.assertEqual(self.connect().status_code, 403)
        response = self.client.post(self.url, {'mode':'local'}, REMOTE_ADDR='203.0.113.5', HTTP_HOST='127.0.0.1:8011')
        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.home / '.codex/config.toml').exists())
        self.assertEqual(ToolToken.objects.count(), 0)

    def test_reconnecting_reuses_saved_live_credential_without_revoking_client(self):
        self.assertEqual(self.connect().status_code, 200)
        path = self.home / '.codex/config.toml'
        saved = path.read_text()
        token = ToolToken.objects.get()
        self.assertEqual(self.connect().status_code, 200)
        token.refresh_from_db()
        self.assertIsNone(token.revoked_at)
        self.assertEqual(ToolToken.objects.count(), 1)
        self.assertEqual(path.read_text(), saved)

    def test_reconnect_does_not_revive_an_explicitly_revoked_credential(self):
        from django.utils import timezone

        self.connect()
        old = ToolToken.objects.get()
        old.revoked_at = timezone.now()
        old.save(update_fields=['revoked_at'])
        self.assertEqual(self.connect().status_code, 200)
        old.refresh_from_db()
        self.assertIsNotNone(old.revoked_at)
        self.assertEqual(ToolToken.objects.filter(revoked_at__isnull=True).count(), 1)

    def test_reconnect_scope_downgrade_revokes_old_execute_permission(self):
        self.connect()
        old = ToolToken.objects.get()
        self.assertEqual(self.connect(scope='read').status_code, 200)
        old.refresh_from_db()
        self.assertIsNotNone(old.revoked_at)
        self.assertEqual(ToolToken.objects.get(revoked_at__isnull=True).scope, 'read')

    def test_explicit_client_home_uses_verified_canonical_profile(self):
        canonical = self.home / 'actual-profile'
        (canonical / '.workbuddy').mkdir(parents=True)
        with override_settings(WORKROOM_CLIENT_CONFIG_HOMES={'workbuddy': str(canonical)}):
            response = self.client.post(self.url.replace('codex/', 'workbuddy/'),
                {'mode':'local', 'scope':'execute'}, HTTP_HOST='127.0.0.1:8011', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue((canonical / '.workbuddy/mcp.json').exists())
        self.assertFalse((self.home / '.workbuddy/mcp.json').exists())

    def test_failed_install_does_not_leave_active_credentials_or_new_instance(self):
        (self.home / '.codex/config.toml').write_text('broken = [')
        response = self.connect()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ToolToken.objects.count(), 0)
        self.assertEqual(Member.objects.count(), 0)

    def test_read_only_and_get_cannot_install(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(self.viewer)
        self.assertEqual(self.connect().status_code, 403)

    def test_csrf_rejects_forged_click(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(browser.post(self.url, {'mode':'local'}, HTTP_HOST='127.0.0.1:8011').status_code, 403)

    @override_settings(WORKROOM_LOCAL_PREVIEW=False)
    def test_download_creates_private_helper_without_touching_server_files(self):
        with patch('apps.projects.quick_connections.available_clients', side_effect=AssertionError('must not inspect server home')):
            response = self.connect(mode='download', platform='windows')
        self.assertEqual(response.status_code, 200)
        self.assertIn('.cmd', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertLess(max(len(line) for line in response.content.splitlines()), 2000)
        self.assertFalse((self.home / '.codex/config.toml').exists())
        self.assertEqual(ToolToken.objects.count(), 1)

    @override_settings(WORKROOM_LOCAL_PREVIEW=False)
    def test_cursor_uses_real_install_scheme_and_keeps_token_out_of_http_url(self):
        import base64
        from urllib.parse import parse_qs, urlsplit

        response = self.client.post(self.url.replace('codex/', 'cursor/'), {'mode':'cursor', 'scope':'read'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        parsed = urlsplit(response.json()['install_url'])
        self.assertEqual(parsed.scheme, 'cursor')
        entry = json.loads(base64.b64decode(parse_qs(parsed.query)['config'][0]))
        self.assertIn('headers', entry)
        self.assertEqual(ToolToken.objects.get().scope, 'read')
        self.assertEqual(Member.objects.get().last_connected_at, None)
