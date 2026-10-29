"""Stateless Streamable HTTP JSON transport and per-request authorization."""

import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.projects.auth_views import _hash_token
from apps.projects.models import Member, Project, ProjectMembership, ToolToken


@override_settings(WORKROOM_MODE="server")
class HttpMcpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mcp-owner")
        self.project = Project.objects.create(name="MCP", goal_title="Ship")
        ProjectMembership.objects.create(project=self.project, user=self.user, role="owner")
        self.member = Member.objects.create(
            project=self.project, kind="external", name="Claude", tool="claude-code"
        )
        self.raw = "wrk_http-mcp-test"
        self.token = ToolToken.objects.create(
            project=self.project,
            user=self.user,
            member=self.member,
            name="Claude",
            scope="execute",
            token_hash=_hash_token(self.raw),
        )

    def rpc(self, method, params=None, **headers):
        return self.client.post(
            "/mcp/",
            json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=params or {})),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.raw,
            HTTP_ACCEPT="application/json, text/event-stream",
            **headers,
        )

    def test_initialize_and_tools_list_and_identity(self):
        response = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["protocolVersion"], "2025-11-25")
        names = {x["name"] for x in self.rpc("tools/list").json()["result"]["tools"]}
        self.assertIn("review_delivery", names)
        result = self.rpc("tools/call", {"name": "whoami", "arguments": {}}).json()["result"]
        self.assertIn("Claude", result["content"][0]["text"])

    def test_no_token_is_401_not_html_redirect(self):
        response = self.client.post("/mcp/", "{}", content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response)

    def test_revoked_membership_invalidates_every_request(self):
        ProjectMembership.objects.filter(project=self.project, user=self.user).delete()
        self.assertEqual(self.rpc("tools/list").status_code, 401)

    def test_read_token_hides_and_denies_writes(self):
        self.token.scope = "read"
        self.token.save()
        names = {x["name"] for x in self.rpc("tools/list").json()["result"]["tools"]}
        self.assertNotIn("create_task", names)
        result = self.rpc(
            "tools/call",
            {
                "name": "create_task",
                "arguments": {"project": str(self.project.pk), "title": "forged"},
            },
        ).json()["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(self.project.tasks.count(), 0)

    def test_bad_origin_and_protocol_are_rejected(self):
        self.assertEqual(
            self.rpc("tools/list", HTTP_ORIGIN="https://evil.example").status_code, 403
        )
        self.assertEqual(
            self.rpc("tools/list", HTTP_MCP_PROTOCOL_VERSION="made-up").status_code, 400
        )

    def test_notification_is_empty_202_and_get_is_405(self):
        response = self.client.post(
            "/mcp/",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.raw,
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b"")
        self.assertEqual(
            self.client.get("/mcp/", HTTP_AUTHORIZATION="Bearer " + self.raw).status_code, 405
        )

    def test_invalid_params_and_unknown_tools_do_not_crash(self):
        self.assertEqual(
            self.rpc("tools/call", {"name": "whoami", "arguments": []}).json()["error"]["code"],
            -32602,
        )
        self.assertEqual(self.rpc("bogus").json()["error"]["code"], -32601)
        self.assertEqual(
            self.rpc("tools/call", {"name": "not_a_tool", "arguments": {}}).json()["error"]["code"],
            -32602,
        )

    def test_cross_project_scope_cannot_be_overridden(self):
        other = Project.objects.create(name="Other", goal_title="Private")
        result = self.rpc(
            "tools/call", {"name": "get_project", "arguments": {"project": str(other.pk)}}
        ).json()["result"]
        self.assertTrue(result["isError"])
