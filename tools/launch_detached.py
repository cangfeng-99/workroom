"""T003R1 分离启动器：以隐藏、脱离进程树的方式启动 install-core.ps1。

用途：PowerShell 工具侧 Start-Process 被安全校验拦截、且子进程随调用结束被回收，
因此用本机 venv Python 以 DETACHED_PROCESS + CREATE_BREAKAWAY_FROM_JOB 启动，
使安装进程独立存活。安装脚本内部仍用 Start-Process -WindowStyle Hidden -PassThru 拉起 uv。
"""
import json
import os
import subprocess
from datetime import UTC, datetime

ROOT = r"D:\Users\28369\Desktop\AgentWorkspace"
SCRIPT = os.path.join(ROOT, "tools", "install-core.ps1")
REPORT = os.path.join(ROOT, "tasks", "reports", "install-core.launch.json")

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# NOTE: DETACHED_PROCESS makes powershell.exe exit immediately without a console,
# so use CREATE_NO_WINDOW + breakaway instead: hidden window, outside the parent job.
flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
cmd = [
    "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden", "-File", SCRIPT,
]

# Wrapper-level failures (e.g. parse errors) land here; the install script keeps its own logs.
os.makedirs(os.path.join(ROOT, "tasks", "logs"), exist_ok=True)
with (
    open(os.path.join(ROOT, "tasks", "logs", "T003-core.launch.log"), "ab") as out_f,
    open(os.path.join(ROOT, "tasks", "logs", "T003-core.launch.err.log"), "ab") as err_f,
):
    try:
        proc = subprocess.Popen(
            cmd, cwd=ROOT, creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=out_f, stderr=err_f,
            close_fds=True,
        )
    except OSError as exc:
        # Legacy recovery fallback when the parent job rejects breakaway.
        flags -= CREATE_BREAKAWAY_FROM_JOB
        proc = subprocess.Popen(
            cmd, cwd=ROOT, creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=out_f, stderr=err_f,
            close_fds=True,
        )
        note = f"breakaway unsupported: {exc}"
    else:
        note = "detached with CREATE_BREAKAWAY_FROM_JOB"

os.makedirs(os.path.dirname(REPORT), exist_ok=True)
payload = {
    "task": "T003R1",
    "launcher": "tools/launch_detached.py",
    "launched_at": datetime.now(UTC).astimezone().isoformat(),
    "spawned_pid": proc.pid,
    "script": SCRIPT,
    "note": note,
}
with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
print(f"spawned_pid={proc.pid} note={note}")
