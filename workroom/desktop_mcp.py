"""Packaged stdio adapter. The GUI owns startup/migrations/restore, not a tool."""

import argparse
import os
from contextlib import nullcontext
from pathlib import Path

import desktop_support as support


class BridgeError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


class DesktopBridge:
    McpError = BridgeError

    def call_tool(self, name, arguments):
        data = Path(os.environ["WORKROOM_DATA_DIR"])
        if not support.running_instance(data, timeout=0):
            raise BridgeError("请先打开 WorkRoom 应用，等工作台启动后重试。")
        import django

        django.setup()
        from apps.projects import mcp
        from apps.projects.tool_api import READ_TOOLS

        readonly = name in READ_TOOLS or name == "read_memory"
        try:
            with nullcontext() if readonly else support.operation_lock(data):
                if not readonly and not support.running_instance(data, timeout=0):
                    raise BridgeError("应用已经关闭，请先重新打开 WorkRoom。")
                return mcp.call_tool(name, arguments)
        except (support.DesktopError, mcp.McpError) as exc:
            raise BridgeError(str(exc)) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="WorkRoom MCP stdio")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    data = support.data_location(os.environ, Path.home(), args.data_dir)
    environment = support.application_environment(os.environ, data)
    for key in list(os.environ):
        if key.startswith("WORKROOM_"):
            os.environ.pop(key)
    os.environ.update(environment)
    os.environ["WORKROOM_DESKTOP_MCP"] = "1"
    from mcp_server import main as serve

    serve()
    return 0
