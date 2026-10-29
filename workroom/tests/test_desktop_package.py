import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import desktop_support as support
from desktop_runtime import DesktopServer


def test_default_data_and_frozen_environment_do_not_use_development_database(tmp_path):
    data = support.data_location({"LOCALAPPDATA": str(tmp_path / "user")}, tmp_path)
    assert data == tmp_path / "user/WorkRoom"
    env = support.application_environment(
        {
            "PATH": "keep",
            "WORKROOM_MODE": "server",
            "WORKROOM_DB_PATH": "private.sqlite3",
            "WORKROOM_SECRET_KEY": "must not inherit",
        },
        data,
    )
    assert env["WORKROOM_MODE"] == "local"
    assert env["WORKROOM_DB_PATH"] == str(data / "db.sqlite3")
    assert env["WORKROOM_DEBUG"] == "0" and env["PATH"] == "keep"
    assert "WORKROOM_SECRET_KEY" not in env


def test_single_instance_lock_is_released_and_shared_with_backups(tmp_path, settings):
    from apps.projects import local_backups

    settings.WORKROOM_MODE = "local"
    settings.DATA_DIR = tmp_path
    with support.instance_lock(tmp_path):
        with pytest.raises(support.InstanceRunning):
            with support.instance_lock(tmp_path):
                pytest.fail("second launcher entered")
        with pytest.raises(local_backups.BackupError, match="运行"):
            with local_backups.instance_lock():
                pytest.fail("CLI entered same data directory")
    with support.instance_lock(tmp_path):
        pass


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000/",
        "http://example.com/",
        "http://127.0.0.1:8/@outside",
        "http://127.0.0.1:8/?x=1",
        "http://127.0.0.1:8/#x",
    ],
)
def test_saved_instance_only_allows_exact_loopback_origin(tmp_path, url):
    record = dict(url=url, launch_id="a" * 32, pid=123)
    (tmp_path / "desktop-instance.json").write_text(json.dumps(record))
    with patch.object(support, "request_status") as request:
        assert support.running_instance(tmp_path, timeout=0) is None
        request.assert_not_called()


def test_running_instance_requires_live_matching_process_nonce(tmp_path):
    record = dict(url="http://127.0.0.1:8123/", launch_id="a" * 32, pid=123)
    (tmp_path / "desktop-instance.json").write_text(json.dumps(record))
    with patch.object(
        support,
        "request_status",
        return_value=dict(application="WorkRoom", launch_id="b" * 32, pid=123),
    ):
        assert support.running_instance(tmp_path, timeout=0) is None
    with patch.object(
        support,
        "request_status",
        return_value=dict(application="WorkRoom", launch_id="a" * 32, pid=123),
    ):
        assert support.running_instance(tmp_path, timeout=0)["url"] == record["url"]


def test_real_loopback_server_serves_static_and_stops(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "hello.css").write_text("body{color:green}")

    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ready"]

    import urllib.request

    server = DesktopServer(app, static)
    server.start()
    url = server.url
    try:
        with urllib.request.urlopen(url + "static/hello.css", timeout=2) as reply:
            assert reply.read() == b"body{color:green}"
        with urllib.request.urlopen(
            url + "_desktop/" + server.launch_id + "/status", timeout=2
        ) as reply:
            assert json.load(reply)["pid"] == os.getpid()
        assert server.host == "127.0.0.1"
    finally:
        server.stop()
    assert not server.thread.is_alive()
    with pytest.raises(OSError):
        urllib.request.urlopen(url, timeout=1)


def test_frozen_settings_honour_explicit_isolated_data_directory(tmp_path):
    app = Path(__file__).resolve().parents[1]
    code = "import sys,json;sys.frozen=True;sys._MEIPASS=sys.argv[1];from config import settings;print(json.dumps({'data':str(settings.DATA_DIR),'db':str(settings.DATABASE_NAME),'bundle':str(settings.BUNDLE_DIR)}))"
    env = dict(
        os.environ,
        PYTHONPATH=str(app),
        WORKROOM_MODE="local",
        WORKROOM_DATA_DIR=str(tmp_path / "isolated"),
        WORKROOM_DB_PATH=str(tmp_path / "isolated/db.sqlite3"),
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "bundle")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    value = json.loads(result.stdout)
    assert Path(value["data"]) == tmp_path / "isolated"
    assert Path(value["db"]).parent == Path(value["data"])
    assert Path(value["bundle"]) == tmp_path / "bundle"


def test_packaged_mcp_parameters_include_data_directory_and_valid_toml(tmp_path, settings):
    import tomllib

    from apps.projects import views

    settings.DATA_DIR = tmp_path / "中文 数据"
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(tmp_path / "WorkRoom.exe")),
    ):
        context = views._connect_context()
    parsed = tomllib.loads(context["config_toml"])["mcp_servers"]["workroom"]
    assert parsed["args"] == ["--mcp", "--data-dir", str(settings.DATA_DIR)]
    assert context["server_path"].endswith("WorkRoom.exe")
    assert parsed["command"] == str(tmp_path / "WorkRoom.exe")


def test_packaged_mcp_refuses_closed_app_before_accessing_database(tmp_path, monkeypatch):
    from desktop_mcp import BridgeError, DesktopBridge

    monkeypatch.setenv("WORKROOM_DATA_DIR", str(tmp_path))
    with pytest.raises(BridgeError, match="先打开 WorkRoom"):
        DesktopBridge().call_tool("list_projects", {})


def test_packaged_mcp_write_waits_for_restore_gate_but_read_does_not(tmp_path, monkeypatch):
    from apps.projects import mcp
    from desktop_mcp import BridgeError, DesktopBridge

    monkeypatch.setenv("WORKROOM_DATA_DIR", str(tmp_path))
    with (
        patch.object(support, "running_instance", return_value={"url": "http://127.0.0.1:1/"}),
        patch.object(mcp, "call_tool", return_value="ok"),
    ):
        with support.operation_lock(tmp_path):
            assert DesktopBridge().call_tool("list_projects", {}) == "ok"
            with pytest.raises(BridgeError, match="恢复"):
                DesktopBridge().call_tool("create_task", {})
        assert DesktopBridge().call_tool("create_task", {}) == "ok"


def test_stdio_entry_speaks_protocol_without_opening_a_window(tmp_path):
    root = Path(__file__).resolve().parents[2]
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_projects", "arguments": {}},
        },
    ]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools/desktop_entry.py"),
            "--mcp",
            "--data-dir",
            str(tmp_path),
        ],
        input="\n".join(json.dumps(x) for x in requests) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=True,
    )
    replies = [json.loads(line) for line in result.stdout.splitlines() if line]
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert replies[1]["result"]["tools"]
    assert replies[2]["result"]["isError"]
    assert "先打开 WorkRoom" in replies[2]["result"]["content"][0]["text"]
    assert not (tmp_path / "db.sqlite3").exists()
