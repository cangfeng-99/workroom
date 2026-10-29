"""Stateless Streamable HTTP, JSON responses; shares stdio schemas and project auth.

No server-initiated requests, SSE stream, sessions, OAuth, or shell execution.
"""

import json

from django.conf import settings
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from tool_schema import TOOLS

from . import mcp, schema_check, tool_api
from .delivery import DeliveryError

VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")


def error(identifier, code, message, status=200):
    return JsonResponse(
        dict(jsonrpc="2.0", id=identifier, error=dict(code=code, message=message)), status=status
    )


def success(identifier, result):
    return JsonResponse(dict(jsonrpc="2.0", id=identifier, result=result))


@csrf_exempt
def endpoint(request):
    response = dispatch(request)
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def dispatch(request):
    origin = request.headers.get("Origin")
    permitted = set(getattr(settings, "CSRF_TRUSTED_ORIGINS", []))
    permitted.add(f"{request.scheme}://{request.get_host()}")
    if origin and origin not in permitted:
        return error(None, -32000, "Origin不被允许。", 403)
    ctx = tool_api.authenticate(request)
    if ctx is None:
        response = error(None, -32001, "项目凭据无效或已撤销。", 401)
        response["WWW-Authenticate"] = 'Bearer realm="workroom"'
        return response
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response
    protocol = request.headers.get("MCP-Protocol-Version", "2025-03-26")
    if protocol not in VERSIONS:
        return error(None, -32600, "不支持的MCP协议版本。", 400)
    accepts = request.headers.get("Accept", "")
    if not all(kind in accepts for kind in ["application/json", "text/event-stream"]):
        return error(None, -32600, "Accept须包含application/json和text/event-stream。", 406)
    if request.content_type != "application/json":
        return error(None, -32600, "需要application/json。", 415)
    try:
        body = request.body
        if len(body) > tool_api.MAX_BODY:
            return error(None, -32600, "请求过大。", 413)
        message = json.loads(body.decode("utf-8"))
    except RequestDataTooBig:
        return error(None, -32600, "请求过大。", 413)
    except (UnicodeDecodeError, ValueError):
        return error(None, -32700, "JSON解析失败。", 400)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return error(None, -32600, "需要单条JSON-RPC 2.0消息。", 400)
    identifier = message.get("id")
    if identifier is not None and (
        isinstance(identifier, bool) or not isinstance(identifier, (str, int))
    ):
        return error(None, -32600, "请求id无效。", 400)
    method = message.get("method")
    if "method" not in message and ("result" in message or "error" in message):
        return HttpResponse(status=202)
    if not isinstance(method, str):
        return error(identifier, -32600, "method必须是字符串。", 400)
    if "id" not in message:
        return HttpResponse(status=202)
    params = message.get("params", {})
    if not isinstance(params, dict):
        return error(identifier, -32602, "params必须是对象。")
    if method == "initialize":
        if (
            not isinstance(params.get("protocolVersion"), str)
            or not isinstance(params.get("capabilities"), dict)
            or not isinstance(params.get("clientInfo"), dict)
        ):
            return error(identifier, -32602, "缺少初始化版本、能力或客户端信息。")
        version = (
            params["protocolVersion"] if params["protocolVersion"] in VERSIONS else VERSIONS[0]
        )
        return success(
            identifier,
            dict(
                protocolVersion=version,
                capabilities={"tools": {}},
                serverInfo={"name": "workroom", "version": "0.2.0"},
                instructions="先whoami验证身份，再读取任务包、认领、汇报和交付；规则变更需确认，完成由负责人验收。",
            ),
        )
    if method == "ping":
        return success(identifier, {})
    allowed = tool_api.READ_TOOLS | (tool_api.EXECUTE_TOOLS if ctx.can_execute else set())
    if method == "tools/list":
        if params.get("cursor"):
            return error(identifier, -32602, "无后续工具分页。")
        return success(identifier, dict(tools=[tool for tool in TOOLS if tool["name"] in allowed]))
    if method != "tools/call":
        return error(identifier, -32601, "未知MCP方法。")
    name = params.get("name")
    tool = next((tool for tool in TOOLS if tool["name"] == name), None)
    if tool is None:
        return error(identifier, -32602, "未知工具。")
    args = params.get("arguments", {})
    clean, problems, warnings = schema_check.check(args, tool["inputSchema"], tool=name)
    if problems:
        return error(
            identifier, -32602, schema_check.explain(name, problems, warnings, tool["inputSchema"])
        )
    args = clean
    if name not in allowed:
        return success(
            identifier,
            dict(content=[dict(type="text", text="该项目令牌没有执行权限。")], isError=True),
        )
    try:
        result = mcp.call_tool(name, args, ctx=ctx)
    except (mcp.McpError, DeliveryError, PermissionError) as exc:
        return success(identifier, dict(content=[dict(type="text", text=str(exc))], isError=True))
    except (ValidationError, ValueError, TypeError, OverflowError):
        return success(
            identifier, dict(content=[dict(type="text", text="工具参数无效。")], isError=True)
        )
    tool_api.mark_success(ctx)
    result = str(result).replace(tool_api._bearer(request), "[REDACTED]")
    return success(identifier, dict(content=[dict(type="text", text=result)], isError=False))
