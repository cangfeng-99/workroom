"""Local installation preserves unrelated configuration and fails closed."""
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from connection_setup import SetupError, install_connection


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for name in ['.codex', '.workbuddy', '.cursor', '.claude']:
            (self.home / name).mkdir()
        self.name = 'workroom-p1-abcdef12'

    def payload(self, tool, token='fixture-token'):
        entry = {'url': 'http://127.0.0.1:8011/mcp/', 'headers': {'Authorization': 'Bearer ' + token}}
        if tool == 'codex':
            configuration = f'[mcp_servers.{self.name}]\nurl = "{entry["url"]}"\nhttp_headers = {{ Authorization = "Bearer {token}" }}\n'
        else:
            configuration = json.dumps({'mcpServers': {self.name: entry}})
        return dict(tool=tool, server_name=self.name, configuration=configuration)

    def test_json_preserves_other_tools_and_settings_with_private_backup(self):
        path = self.home / '.workbuddy/mcp.json'
        original = {'theme': 'dark', 'mcpServers': {'workroom': {'command': 'old'}, 'other': {'url': 'https://example.org'}}}
        path.write_text(json.dumps(original), encoding='utf-8')
        install_connection(self.payload('workbuddy'), home=self.home)
        current = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(current['theme'], 'dark')
        self.assertEqual(current['mcpServers']['workroom'], original['mcpServers']['workroom'])
        self.assertEqual(current['mcpServers']['other'], original['mcpServers']['other'])
        self.assertIn(self.name, current['mcpServers'])
        self.assertEqual(json.loads(next(path.parent.glob('*.bak-*')).read_text()), original)

    def test_codex_preserves_multiline_comments_and_updates_only_owned_block(self):
        path = self.home / '.codex/config.toml'
        original = '# keep comments\nmodel = "chosen"\nprompt = """\n[mcp_servers.fake]\nThis is text\n"""\n[mcp_servers.workroom]\ncommand = "old"\n'
        path.write_text(original, encoding='utf-8')
        install_connection(self.payload('codex'), home=self.home)
        install_connection(self.payload('codex', 'new-token'), home=self.home)
        text = path.read_text(encoding='utf-8')
        self.assertTrue(text.startswith(original.rstrip()))
        parsed = tomllib.loads(text)
        self.assertEqual(parsed['model'], 'chosen')
        self.assertEqual(parsed['mcp_servers']['workroom']['command'], 'old')
        self.assertEqual(parsed['mcp_servers'][self.name]['http_headers']['Authorization'], 'Bearer new-token')
        self.assertEqual(text.count(f'[mcp_servers.{self.name}]'), 1)

    def test_invalid_json_or_unowned_toml_collision_does_not_overwrite(self):
        for tool, relative, original in [('cursor', '.cursor/mcp.json', '{broken'), ('codex', '.codex/config.toml', f'[mcp_servers.{self.name}]\ncommand="user-owned"\n')]:
            with self.subTest(tool=tool):
                path = self.home / relative
                path.write_text(original, encoding='utf-8')
                with self.assertRaises(SetupError):
                    install_connection(self.payload(tool), home=self.home)
                self.assertEqual(path.read_text(), original)

    def test_claude_uses_user_config_without_touching_project_files(self):
        path = self.home / '.claude.json'
        path.write_text('{"projects":{"existing":{"enabled":true}}}', encoding='utf-8')
        install_connection(self.payload('claude-code'), home=self.home)
        self.assertTrue(json.loads(path.read_text())['projects']['existing']['enabled'])
        self.assertIn(self.name, json.loads(path.read_text())['mcpServers'])

    def test_unknown_client_and_missing_installation_do_not_create_config(self):
        with self.assertRaises(SetupError):
            install_connection(self.payload('../outside'), home=self.home)
        (self.home / '.cursor').rmdir()
        with self.assertRaises(SetupError):
            install_connection(self.payload('cursor'), home=self.home)
        self.assertFalse((self.home / '.cursor').exists())

    def test_linked_config_does_not_modify_the_other_file(self):
        path = self.home / '.cursor/mcp.json'
        target = self.home / 'other.json'
        target.write_text('{}')
        path.hardlink_to(target)
        with self.assertRaises(SetupError):
            install_connection(self.payload('cursor'), home=self.home)
        self.assertEqual(target.read_text(), '{}')

    def test_in_progress_install_is_not_overwritten(self):
        lock = self.home / '.codex/config.toml.workroom-lock'
        lock.write_text('fixture')
        with self.assertRaises(SetupError):
            install_connection(self.payload('codex'), home=self.home)
        self.assertEqual(lock.read_text(), 'fixture')
        self.assertFalse((self.home / '.codex/config.toml').exists())

    def test_downloaded_helper_runs_in_an_isolated_user_profile(self):
        from apps.projects.quick_connections import helper_download

        native = 'windows' if os.name == 'nt' else 'linux'
        response = helper_download(self.payload('codex'), native)
        helper = self.home / ('connect.cmd' if os.name == 'nt' else 'connect.sh')
        helper.write_bytes(response.content)
        temp = self.home / 'temp'
        temp.mkdir()
        env = dict(os.environ, USERPROFILE=str(self.home), HOME=str(self.home), TEMP=str(temp), TMP=str(temp))
        if os.name == 'nt':
            launcher = self.home / 'bin'
            launcher.mkdir()
            (launcher / 'py.cmd').write_text(f'@echo off\r\n"{sys.executable}" %2\r\n', encoding='utf-8')
            env['PATH'] = str(launcher) + ';' + env['PATH']
        command = ['cmd.exe', '/d', '/c', str(helper)] if os.name == 'nt' else ['sh', str(helper)]
        result = subprocess.run(command, cwd=self.home, env=env, input=b'\n', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8', errors='replace'))
        installed = tomllib.loads((self.home / '.codex/config.toml').read_text(encoding='utf-8'))
        self.assertIn(self.name, installed['mcp_servers'])
        self.assertFalse(list(temp.glob('*.py')))
