"""Remote MCP uses HTTPS, sends no credentials in URLs, and skips Django."""
import io
import os
from unittest.mock import patch

from django.test import SimpleTestCase

from remote_bridge import RemoteBridge, RemoteError


class RemoteTests(SimpleTestCase):
    def test_rejects_plain_remote_http_and_credential_urls(self):
        for url in ['http://example.com','https://user:pass@example.com','https://example.com/?secret=x']:
            with self.assertRaises(RemoteError):
                RemoteBridge(url,'wrk_test')

    def test_https_forwards_json_and_redacts_token(self):
        bridge = RemoteBridge('https://example.com','wrk_test')
        with patch.object(bridge.opener,'open',return_value=io.BytesIO(b'{"ok":true,"result":"wrk_test"}')) as call:
            self.assertEqual(bridge.call_tool('get_project',{'project':'1'}),'[REDACTED]')
        request = call.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'),'Bearer wrk_test')
        self.assertNotIn('wrk_test',request.full_url)

    def test_remote_loader_never_sets_up_local_django(self):
        import mcp_server
        previous = mcp_server._mcp_module
        try:
            mcp_server._mcp_module = None
            with patch.dict(os.environ,{'WORKROOM_SERVER_URL':'https://example.com','WORKROOM_ACCESS_TOKEN':'wrk_test'}), patch('django.setup',side_effect=AssertionError('local setup forbidden')):
                self.assertIsInstance(mcp_server._load(),RemoteBridge)
        finally:
            mcp_server._mcp_module = previous

    def test_tool_schema_includes_context_evidence_and_heartbeat(self):
        import mcp_server
        tools = {x['name']:x for x in mcp_server.TOOLS}
        self.assertIn('get_task_context',tools)
        self.assertIn('confirm_task_context',tools)
        self.assertIn('heartbeat_task',tools)
        self.assertIn('test_output',tools['submit_result']['inputSchema']['properties'])
