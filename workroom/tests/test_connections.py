"""A brand can have multiple users/devices, each with its own credentials."""

import json
import tomllib

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.test.client import RequestFactory

from apps.projects.models import Member, Project, ProjectMembership, ToolToken


@override_settings(WORKROOM_MODE="server")
class ConnectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("connection-owner")
        self.editor = User.objects.create_user("connection-editor")
        self.viewer = User.objects.create_user("connection-viewer")
        self.project = Project.objects.create(name="Shared", goal_title="Ship")
        for user, role in [(self.owner, "owner"), (self.editor, "editor"), (self.viewer, "viewer")]:
            ProjectMembership.objects.create(project=self.project, user=user, role=role)
        self.url = f"/p/{self.project.pk}/connections/"

    def create(self, user, **extra):
        self.client.force_login(user)
        return self.client.post(
            self.url,
            {
                "action": "add",
                "tool": "claude-code",
                "device_name": "My Mac",
                "platform": "mac",
                "name": "Claude on Mac",
                "capabilities": ["code_read", "tests"],
                **extra,
            },
        )

    def test_same_brand_has_distinct_connection_instances(self):
        self.assertEqual(self.create(self.owner).status_code, 302)
        self.assertEqual(self.create(self.editor).status_code, 302)
        members = list(self.project.members.filter(kind="external"))
        self.assertEqual(len(members), 2)
        self.assertNotEqual(members[0].connection_id, members[1].connection_id)
        self.assertEqual({m.connection_user_id for m in members}, {self.owner.pk, self.editor.pk})

    def test_custom_mcp_client_can_be_added(self):
        response = self.create(self.owner, tool="custom", custom_tool="my-agent", name="My client")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Member.objects.filter(project=self.project, tool="my-agent").exists())

    def test_export_uses_each_clients_documented_configuration_contract(self):
        from apps.projects.connection_views import configuration

        request = RequestFactory().get(self.url)
        raw = "wrk_export-contract-fixture"
        for tool in ["codex", "claude-code", "cursor", "workbuddy", "harness", "my-agent"]:
            with self.subTest(tool=tool):
                member = Member(tool=tool, platform="mac")
                text, command = configuration(request, member, raw)
                if tool == "codex":
                    entry = tomllib.loads(text)["mcp_servers"]["workroom"]
                    headers = entry["http_headers"]
                elif tool == "harness":
                    row = json.loads(text)[0]
                    self.assertEqual(row["name"], "@deepseek-ai/dsh-mcp-client")
                    entry = row["config"]
                    self.assertEqual(entry["serverName"], "workroom")
                    self.assertEqual(entry["transport"], "streamable-http")
                    headers = entry["headers"]
                else:
                    entry = json.loads(text)["mcpServers"]["workroom"]
                    if tool in {"cursor", "workbuddy"}:
                        self.assertNotIn("type", entry)
                    else:
                        self.assertEqual(entry["type"], "http")
                    headers = entry["headers"]
                self.assertEqual(entry["url"], "http://testserver/mcp/")
                self.assertEqual(headers, {"Authorization": "Bearer " + raw})
                self.assertEqual(bool(command), tool == "claude-code")

    def test_real_form_preserves_csrf_and_same_origin_submission(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        page = browser.get(self.url)
        self.assertNotEqual(
            page["Referrer-Policy"],
            "no-referrer",
            "No-referrer makes browsers omit the origin/referrer needed for form CSRF.",
        )
        data = {
            "action": "add",
            "tool": "claude-code",
            "name": "CSRF form",
            "device_name": "Mac",
            "platform": "mac",
            "csrfmiddlewaretoken": browser.cookies["workroom_csrftoken"].value,
        }
        self.assertEqual(
            browser.post(self.url, data, HTTP_ORIGIN="http://testserver").status_code, 302
        )
        self.assertEqual(browser.post(self.url, data, HTTP_ORIGIN="null").status_code, 403)

    def test_legacy_team_page_cannot_issue_another_users_instance_token(self):
        self.create(self.editor)
        member = self.project.members.get(kind="external")
        self.client.force_login(self.owner)
        self.client.post(
            f"/p/{self.project.pk}/team/",
            {
                "action": "token",
                "member": member.pk,
                "scope": "execute",
                "name": "forged",
            },
        )
        self.assertEqual(ToolToken.objects.count(), 0)

    def test_existing_wrong_owner_token_is_also_rejected(self):
        from apps.projects.auth_views import _hash_token

        self.create(self.editor)
        member = self.project.members.get(kind="external")
        raw = "wrk_mismatched-owner"
        ToolToken.objects.create(
            project=self.project,
            user=self.owner,
            member=member,
            scope="execute",
            name="forged",
            token_hash=_hash_token(raw),
        )
        response = self.client.post(
            "/api/tools/whoami/",
            "{}",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + raw,
        )
        self.assertEqual(response.status_code, 401)

    def test_viewer_and_outsider_cannot_create_connections(self):
        self.assertEqual(self.create(self.viewer).status_code, 403)
        outsider = User.objects.create_user("connection-outsider")
        self.assertEqual(self.create(outsider).status_code, 404)

    def test_cannot_issue_credentials_for_another_users_instance(self):
        self.create(self.owner)
        member = self.project.members.get(kind="external")
        self.client.force_login(self.editor)
        response = self.client.post(
            self.url, {"action": "configure", "member": member.pk, "scope": "execute"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ToolToken.objects.count(), 0)

    def test_configuration_is_private_and_uses_client_local_paths(self):
        self.create(self.owner)
        member = self.project.members.get(kind="external")
        response = self.client.post(
            self.url, {"action": "configure", "member": member.pk, "scope": "execute"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        config = response.context["configuration"]
        self.assertNotIn("D:\\Users", config)
        self.assertEqual(ToolToken.objects.get().user_id, self.owner.pk)

    def test_failed_call_does_not_mark_a_connection_successful(self):
        from apps.projects.auth_views import _hash_token

        self.create(self.owner)
        member = self.project.members.get(kind="external")
        raw = "wrk_connection-test"
        token = ToolToken.objects.create(
            project=self.project,
            user=self.owner,
            member=member,
            token_hash=_hash_token(raw),
            scope="read",
            name="test",
        )
        response = self.client.post(
            "/api/tools/claim_task/",
            data=json.dumps({"project": str(self.project.pk), "task": "1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + raw,
        )
        self.assertEqual(response.status_code, 403)
        token.refresh_from_db()
        self.assertIsNone(token.last_seen_at)
        response = self.client.post(
            "/api/tools/whoami/",
            "{}",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + raw,
        )
        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertIsNotNone(member.last_connected_at)
