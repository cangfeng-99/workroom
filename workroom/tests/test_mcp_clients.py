"""Tests for one-click MCP client configuration."""

from __future__ import annotations

import json
import shutil
import tempfile
import tomllib
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects import mcp_clients


class McpClientTests(TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        for name in ('.cursor', '.codex', '.workbuddy'):
            (self.tmp / name).mkdir()
        self.override = override_settings(MCP_HOME=self.tmp)
        self.override.enable()

    def tearDown(self) -> None:
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_merge_keeps_other_keys_and_backs_up(self) -> None:
        path = self.tmp / '.cursor' / 'mcp.json'
        path.write_text(
            json.dumps(
                {'mcpServers': {'other': {'command': 'x'}}, 'theme': 'dark'},
                ensure_ascii=False,
            ),
            encoding='utf-8',
        )
        mcp_clients.connect('cursor')

        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertIn('other', data['mcpServers'])
        self.assertIn('workroom', data['mcpServers'])
        self.assertEqual(data['theme'], 'dark')
        self.assertEqual(len(list((self.tmp / '.cursor').glob('mcp.json.bak-*'))), 1)

    def test_toml_replaces_only_the_workroom_section(self) -> None:
        path = self.tmp / '.codex' / 'config.toml'
        path.write_text(
            '[model]\nname = "x"\n\n'
            '[mcp_servers.workroom]\ncommand = "old"\nargs = []\n\n'
            '[mcp_servers.other]\ncommand = "y"\n',
            encoding='utf-8',
        )
        mcp_clients.connect('codex')

        text = path.read_text(encoding='utf-8')
        self.assertNotIn('"old"', text)
        self.assertEqual(text.count('[mcp_servers.workroom]'), 1)
        data = tomllib.loads(text)
        self.assertEqual(data['model']['name'], 'x')
        self.assertEqual(data['mcp_servers']['other']['command'], 'y')
        self.assertIn('workroom', data['mcp_servers'])

    def test_status_marks_configured_client(self) -> None:
        (self.tmp / '.workbuddy' / 'mcp.json').write_text(
            json.dumps({'mcpServers': {'workroom': {}}}), encoding='utf-8'
        )
        items = {item['key']: item for item in mcp_clients.status()}
        self.assertTrue(items['workbuddy']['configured'])
        self.assertFalse(items['cursor']['configured'])

    def test_missing_client_raises(self) -> None:
        shutil.rmtree(self.tmp / '.cursor')
        with self.assertRaises(mcp_clients.ClientError):
            mcp_clients.connect('cursor')

    def test_view_writes_config(self) -> None:
        response = self.client.post(
            reverse('projects:connect_client', args=['cursor'])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('已写入', response.content.decode('utf-8'))
        data = json.loads((self.tmp / '.cursor' / 'mcp.json').read_text('utf-8'))
        self.assertIn('workroom', data['mcpServers'])
