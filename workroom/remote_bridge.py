"""Dependency-free stdio-client to authenticated WorkRoom HTTPS tool API."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RemoteError(Exception):
    @property
    def message(self):
        return str(self)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RemoteBridge:
    McpError = RemoteError

    def __init__(self, url=None, token=None):
        self.base = (url or os.environ.get("WORKROOM_SERVER_URL", "")).rstrip("/")
        self.token = token or os.environ.get("WORKROOM_ACCESS_TOKEN", "")
        parts = urlsplit(self.base)
        loopback = parts.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            parts.scheme != "https" and not (parts.scheme == "http" and loopback)
        ) or not parts.hostname:
            raise RemoteError("服务器地址必须使用 HTTPS；HTTP 仅允许本机回环测试。")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise RemoteError("服务器地址不能包含凭据、查询参数或片段。")
        if not self.token.startswith("wrk_") or any(
            ord(x) < 33 or ord(x) > 126 for x in self.token
        ):
            raise RemoteError("请配置有效的 WORKROOM_ACCESS_TOKEN。")
        self.opener = build_opener(NoRedirect())

    def call_tool(self, name, arguments):
        if not isinstance(arguments, dict):
            raise RemoteError("工具参数必须是对象。")
        body = json.dumps(arguments, ensure_ascii=False).encode("utf-8")
        if len(body) > 65536:
            raise RemoteError("请求参数超过 64 KiB。")
        request = Request(
            self.base + "/api/tools/" + quote(name, safe="") + "/",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(512 * 1024 + 1)
        except HTTPError as exc:
            raise RemoteError(
                f"服务器拒绝请求（HTTP {exc.code}），请核对令牌权限和任务状态。"
            ) from None
        except (URLError, OSError, ValueError):
            raise RemoteError("无法连接服务器，请检查 HTTPS 证书、网络和服务器状态。") from None
        if len(raw) > 512 * 1024:
            raise RemoteError("服务器响应过大，请分页读取。")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise RemoteError("服务器响应不是有效 JSON。") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RemoteError("服务器未确认请求成功。")
        return str(payload.get("result", "")).replace(self.token, "[REDACTED]")
