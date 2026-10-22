#!/usr/bin/env python3
"""T004: corrected environment runner for the local dev venv.

Why this file exists
--------------------
`tools/install-core.ps1` (T003R1) reported status=FAILED with an empty exit code.
Root cause: `Start-Process -PassThru` + `-NoNewWindow` + output redirection leaves
`Process.ExitCode` unset (null) after `WaitForExit()`, so `$exitCode -eq 0` was false
even though uv exited 0 and the packages were installed. The PowerShell record is
kept unchanged as history; this script judges state from real subprocess return
codes instead of guessing.

Usage (real interpreter, not the venv interpreter):
  CP312="C:/Users/28369/AppData/Roaming/uv/python/cpython-3.12.14-windows-x86_64-none/python.exe"
  "$CP312" tools/install-core.py            # verify + freeze lock (no reinstall)
  "$CP312" tools/install-core.py --install  # full install, then verify + freeze

No secrets, no network calls of its own, no Chromium download, no database work.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = r"D:\Users\28369\Desktop\AgentWorkspace"
VENV_PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
UV = r"C:\Users\28369\.local\bin\uv.exe"
REQ = os.path.join(ROOT, "requirements-dev.in")
LOCK = os.path.join(ROOT, "requirements-dev.lock")
LOG_DIR = os.path.join(ROOT, "tasks", "logs")
REPORT_DIR = os.path.join(ROOT, "tasks", "reports")
REPORT = os.path.join(REPORT_DIR, "env-verify.json")
CST = timezone(timedelta(hours=8))

IMPORT_CHECK = (
    "import importlib, json\n"
    "from importlib.metadata import version, PackageNotFoundError\n"
    "pairs = [('django','Django'), ('pytest','pytest'), ('pytest_django','pytest-django'),\n"
    "         ('ruff','ruff'), ('MySQLdb','mysqlclient'), ('playwright','playwright')]\n"
    "out = {'imports': {}, 'dist_versions': {}}\n"
    "for mod, dist in pairs:\n"
    "    importlib.import_module(mod)\n"
    "    out['imports'][mod] = 'ok'\n"
    "    try:\n"
    "        out['dist_versions'][dist] = version(dist)\n"
    "    except PackageNotFoundError:\n"
    "        out['dist_versions'][dist] = None\n"
    "print(json.dumps(out))\n"
)


def now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def run(cmd: list[str], log_path: str, timeout: int = 240) -> dict:
    """Run one command, capture the real return code, tee output to a log file."""
    started = now()
    try:
        proc = subprocess.run(
            cmd, check=False, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        code, timed_out = -1, True
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# cmd: {subprocess.list2cmdline(cmd)}\n")
        fh.write(f"# started: {started}\n# exit_code: {code}\n")
        fh.write("# --- stdout ---\n" + out + "\n# --- stderr ---\n" + err + "\n")
    return {
        "cmd": subprocess.list2cmdline(cmd),
        "exit_code": code,
        "timed_out": timed_out,
        "stdout_tail": "\n".join(out.strip().splitlines()[-20:]),
        "stderr_tail": "\n".join(err.strip().splitlines()[-10:]),
        "log": log_path,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true",
                    help="run uv pip install first (default: verify only)")
    args = ap.parse_args()

    for path in (VENV_PY, UV):
        if not os.path.isfile(path):
            print(f"missing required interpreter/tool: {path}", file=sys.stderr)
            return 2
    os.makedirs(REPORT_DIR, exist_ok=True)

    steps: list[dict] = []
    if args.install:
        steps.append(run([
            UV, "pip", "install", "--python", VENV_PY, "-r", REQ,
            "--default-index", "https://pypi.org/simple",
            "--only-binary", "mysqlclient",
        ], os.path.join(LOG_DIR, "T004-install.log"), timeout=600))

    freeze = run([UV, "pip", "freeze", "--python", VENV_PY],
                 os.path.join(LOG_DIR, "T004-freeze.log"))
    lock_written = False
    if freeze["exit_code"] == 0:
        # full stdout was tee'd to the log; rebuild the lock from its stdout block
        with open(freeze["log"], encoding="utf-8") as fh:
            body = fh.read()
        stdout_block = body.split("# --- stdout ---\n", 1)[1].split("\n# --- stderr ---", 1)[0]
        with open(LOCK, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(stdout_block.rstrip("\n") + "\n")
        lock_written = True
    steps.append(freeze)

    imports = run([VENV_PY, "-c", IMPORT_CHECK],
                  os.path.join(LOG_DIR, "T004-imports.log"))
    steps.append(imports)

    versions = {}
    if imports["exit_code"] == 0:
        try:
            versions = json.loads(imports["stdout_tail"].splitlines()[-1])
        except (ValueError, IndexError):
            versions = {}

    install_ok = all(s["exit_code"] == 0 for s in (steps if args.install else []))
    ok = lock_written and imports["exit_code"] == 0 and install_ok
    report = {
        "task": "T004",
        "checked_at": now(),
        "status": "SUCCESS" if ok else "FAILED",
        "reinstall_performed": args.install,
        "active_installer_pids_before_run": "27208, 28004, 29472, 7880 all absent (T004 precheck)",
        "py_scripts_interpreter": sys.executable,
        "venv_python": VENV_PY,
        "uv": UV,
        "steps": steps,
        "import_versions": versions,
        "lock_file": LOCK if lock_written else None,
        "lock_lines": len(Path(LOCK).read_text(encoding="utf-8").splitlines()) if lock_written else 0,
        "correction": (
            "tasks/reports/install-core.json (T003R1) says status=FAILED with exit_code=null. "
            "That was a false negative: PowerShell Start-Process -PassThru with redirected output "
            "left Process.ExitCode unset after WaitForExit(). uv actually exited 0 "
            "(T003-core.err.log: 'Installed 1 package ... + django==5.2.18'). "
            "The historical report is intentionally left unmodified; this file is the corrected state."
        ),
        "chromium_downloaded": False,
        "database_created": False,
        "secrets_used": False,
    }
    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(json.dumps({"status": report["status"], "freeze": freeze["exit_code"],
                      "imports": imports["exit_code"], "versions": versions,
                      "report": REPORT}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
