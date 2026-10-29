"""Client-specific configuration rendering, shared by manual and quick setup."""
import json

from django.urls import reverse


def configuration(request, member, raw, *, transport="http", server_name="workroom"):
    if transport == "http":
        entry = dict(
            type="http",
            url=request.build_absolute_uri(reverse("projects:mcp_http")),
            headers={"Authorization": "Bearer " + raw},
        )
    else:
        entry = dict(
            type="stdio",
            command="python" if member.platform == "windows" else "python3",
            args=["<本机桥接目录>/mcp_server.py"],
            env=dict(
                WORKROOM_SERVER_URL=request.build_absolute_uri("/").rstrip("/"),
                WORKROOM_ACCESS_TOKEN=raw,
            ),
        )
    if member.tool == "codex":
        if transport == "http":
            text = (
                f"[mcp_servers.{server_name}]\nurl = "
                + json.dumps(entry["url"])
                + "\nhttp_headers = { Authorization = "
                + json.dumps("Bearer " + raw)
                + " }\n"
            )
        else:
            text = (
                f"[mcp_servers.{server_name}]\ncommand = "
                + json.dumps(entry["command"])
                + "\nargs = "
                + json.dumps(entry["args"], ensure_ascii=False)
                + f"\n[mcp_servers.{server_name}.env]\n"
            )
            text += "\n".join(
                key + " = " + json.dumps(val, ensure_ascii=False)
                for key, val in entry["env"].items()
            )
    elif member.tool == "harness":
        # Cordis loads plugin entries, not an mcpServers object. JSON is valid YAML.
        entry.pop("type")
        entry["serverName"] = server_name
        entry["transport"] = "streamable-http" if transport == "http" else "stdio"
        text = json.dumps(
            [{"id": "mcp-" + server_name, "name": "@deepseek-ai/dsh-mcp-client", "config": entry}],
            ensure_ascii=False,
            indent=2,
        )
    else:
        if member.tool in {"cursor", "workbuddy"} and transport == "http":
            # WorkBuddy 5.9.2's own UserMcpFile.toEntry writes HTTP as url/headers.
            entry.pop("type")
        text = json.dumps({"mcpServers": {server_name: entry}}, ensure_ascii=False, indent=2)
    command = ""
    if member.tool == "claude-code" and transport == "http":
        command = f'claude mcp add --transport http {server_name} {entry["url"]} --header "Authorization: Bearer {raw}"'
    return text, command


