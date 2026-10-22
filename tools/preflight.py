"""Repeatable local preflight: zero network, zero product code.

Checks development tooling, local service reachability, skill/expert presence,
plan/rule revisions, secret hygiene, a temporary-file round trip, a Django
system check with an ephemeral in-memory configuration, and a browser smoke
test using an installed Chrome/Edge channel (no browser download).

This is tooling readiness only. It is NOT a product test, NOT a database
acceptance test, and NOT a permission-sandbox acceptance test.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "tasks" / "reports" / "preflight.json"
RUNTIME = Path(r"C:\Users\28369\.cache\codex-runtimes\codex-primary-runtime\dependencies")
PATH_DIRS = [
    ROOT / ".venv" / "Scripts",
    RUNTIME / "node" / "bin",
    RUNTIME / "bin" / "fallback",
    Path(r"C:\Users\28369\.local\bin"),
]
SKILLS = ("webapp-testing", "python-testing-patterns")
EXPERT = Path(r"C:\Users\28369\.workbuddy\plugins\marketplaces\my-experts\plugins\agentworkspace-fullstack-executor")

results = {}


def add(key, status, **extra):
    results[key] = {"status": status, **extra}


def run(cmd, timeout=60, cwd=None, env=None):
    return subprocess.run(
        cmd, check=False, capture_output=True, text=True, timeout=timeout, cwd=cwd or ROOT,
        env=env, encoding="utf-8", errors="replace",
    )


def check_python():
    version = sys.version.split()[0]
    in_venv = Path(sys.executable).resolve().is_relative_to((ROOT / ".venv").resolve())
    add("python", "PASS" if in_venv else "WARN", version=version,
        executable=sys.executable, in_project_venv=in_venv)

    missing = []
    versions = {}
    for mod in ("django", "pytest", "pytest_django", "ruff", "MySQLdb", "playwright"):
        try:
            m = __import__(mod)
            versions[mod] = getattr(m, "__version__", "unknown")
        except ImportError as exc:
            missing.append(f"{mod}: {type(exc).__name__}")
    add("python_imports", "PASS" if not missing else "FAIL",
        modules=versions, missing=missing)


def tool_env():
    env = os.environ.copy()
    env["PATH"] = ";".join(str(p) for p in PATH_DIRS) + ";" + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    return env


def check_tools():
    env = tool_env()
    specs = {"node": ["node", "--version"], "pnpm": ["pnpm", "--version"], "git": ["git", "--version"]}
    found = {}
    for name, cmd in specs.items():
        exe = shutil.which(cmd[0], path=env["PATH"])
        if not exe:
            found[name] = {"status": "FAIL", "error": "not found on PATH"}
            continue
        try:
            argv = ["cmd", "/c", exe, cmd[1]] if exe.lower().endswith((".cmd", ".bat")) else [exe, cmd[1]]
            r = run(argv, timeout=30, env=env)
            out = (r.stdout or r.stderr).strip()
            found[name] = {"status": "PASS" if r.returncode == 0 else "FAIL",
                           "version": out.splitlines()[0] if out else "", "path": exe}
        except (OSError, subprocess.TimeoutExpired) as exc:
            found[name] = {"status": "FAIL", "error": type(exc).__name__}

    pnpm_v = found.get("pnpm", {}).get("version", "")
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", pnpm_v or "")
    if m:
        found["pnpm"]["major"] = int(m.group(1))
        found["pnpm"]["expected_major_ok"] = int(m.group(1)) == 11
        if int(m.group(1)) != 11:
            found["pnpm"]["status"] = "WARN"
            found["pnpm"]["note"] = "resolved pnpm is not 11.x; check PATH order"
    add("node_pnpm_git", "PASS" if all(v.get("status") in ("PASS", "WARN") for v in found.values()) else "FAIL",
        tools=found)


def check_mysql():
    try:
        r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-Service -Name MySQL80 -ErrorAction Stop).Status"], timeout=30)
        svc = (r.stdout or "").strip()
        add("mysql_service", "PASS" if svc == "Running" else "FAIL",
            service="MySQL80", state=svc or "unknown", exit_code=r.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        add("mysql_service", "FAIL", service="MySQL80", error=type(exc).__name__)

    try:
        with socket.create_connection(("127.0.0.1", 3306), timeout=2):
            add("mysql_port_3306", "PASS", listening=True, target="127.0.0.1:3306")
    except OSError as exc:
        add("mysql_port_3306", "FAIL", listening=False, error=type(exc).__name__)

    env_file = ROOT / ".env"
    has_creds = env_file.is_file() and "MYSQL_PASSWORD" in env_file.read_text(encoding="utf-8", errors="replace")
    add("mysql_login", "NOT_CONFIGURED" if not has_creds else "NOT_VERIFIED",
        detail=("no local .env with MYSQL_* credentials; login not attempted, not guessed"
                if not has_creds else "credentials file present but login not attempted in preflight"),
        login_attempted=False,
        scope_note="port/service checks are reachability only, not authentication")


def check_skills():
    rows = {}
    for base in (Path(r"C:\Users\28369\.codex\skills"), Path(r"C:\Users\28369\.workbuddy\skills")):
        rows[str(base)] = {name: (base / name / "SKILL.md").is_file() for name in SKILLS}
    ok = all(all(v.values()) for v in rows.values())
    add("skills_both_sides", "PASS" if ok else "FAIL", expected=list(SKILLS), installed=rows)


def check_expert():
    agents = list((EXPERT / "agents").glob("*.md")) if EXPERT.is_dir() else []
    avatar = (EXPERT / "avatars" / "expert.png").is_file()
    readme = (EXPERT / "README.md").is_file()
    frontmatter = False
    if agents:
        head = agents[0].read_text(encoding="utf-8", errors="replace").lstrip()
        frontmatter = head.startswith("---")
    structural = bool(agents) and avatar and readme and frontmatter
    add("expert_package", "PASS" if structural else "FAIL",
        path=str(EXPERT), agents=[a.name for a in agents], avatar=avatar,
        readme=readme, yaml_frontmatter=frontmatter)
    validator = Path(r"D:\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\expert-manager\scripts\validate_expert.py")
    try:
        checked = run([sys.executable, str(validator), str(EXPERT)], env=tool_env())
        add("expert_native_validator", "PASS" if checked.returncode == 0 else "FAIL",
            exit_code=checked.returncode, validator_invoked=True,
            gui_visibility="NOT_VERIFIED", output=(checked.stdout + checked.stderr)[-500:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        add("expert_native_validator", "FAIL", error=type(exc).__name__,
            validator_invoked=False, gui_visibility="NOT_VERIFIED")


def check_plan_rules():
    plan = (ROOT / "tasks" / "plan.md").read_text(encoding="utf-8", errors="replace")
    rules = (ROOT / "CONSTRAINTS.md").read_text(encoding="utf-8", errors="replace")
    plan_match = re.search(r"PLAN-r\d+", plan)
    rules_match = re.search(r"RULES-r\d+", rules)
    plan_ok = plan_match is not None
    rules_ok = rules_match is not None
    add("plan_rules", "PASS" if plan_ok and rules_ok else "FAIL",
        plan=plan_match.group() if plan_ok else "MISSING", rules=rules_match.group() if rules_ok else "MISSING",
        plan_is_draft=("草案" in plan or "DRAFT" in plan.upper()))


def check_gitignore():
    gi = ROOT / ".gitignore"
    text = gi.read_text(encoding="utf-8", errors="replace") if gi.is_file() else ""
    has_env = any(line.strip() in (".env", ".env.*") for line in text.splitlines())
    has_example = "!.env.example" in text
    ignored = None
    try:
        r = run(["git", "check-ignore", "-q", ".env"], timeout=20)
        ignored = r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ignored = None
    local_config_present = (ROOT / ".env").is_file()
    tracked = run(["git", "ls-files", "--error-unmatch", ".env"], timeout=20).returncode == 0
    ok = has_env and has_example and ignored is True and not tracked
    add("gitignore_secrets", "PASS" if ok else "FAIL",
        ignores_env=ignored, negates_example=has_example,
        real_env_present=local_config_present, real_env_tracked=tracked)


def check_temp_io():
    d = Path(tempfile.mkdtemp(prefix="aw-preflight-"))
    probe = d / "probe.txt"
    payload = "agentworkspace-preflight"
    try:
        probe.write_text(payload, encoding="utf-8")
        read_back = probe.read_text(encoding="utf-8")
        size = probe.stat().st_size
        probe.unlink()
        cleanup = True
    finally:
        shutil.rmtree(d, ignore_errors=True)
    add("temp_dir_io", "PASS" if read_back == payload and size > 0 and cleanup and not d.exists() else "FAIL",
        path=str(d) + " (removed)", read_back_ok=read_back == payload, cleaned=not d.exists(),
        note="temporary directory only; NOT a product permission-sandbox acceptance")


def check_django():
    code = (
        "import django\n"
        "from django.conf import settings\n"
        "settings.configure(DEBUG=True, SECRET_KEY='preflight-only-not-secret', "
        "DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}, "
        "INSTALLED_APPS=[], USE_TZ=True)\n"
        "django.setup()\n"
        "from django.core.management import call_command\n"
        "call_command('check', verbosity=2)\n"
    )
    try:
        r = run([sys.executable, "-c", code], timeout=60, env=tool_env())
        add("django_system_check", "PASS" if r.returncode == 0 else "FAIL",
            exit_code=r.returncode, settings="ephemeral in-memory sqlite, not project settings",
            output=(r.stdout or r.stderr).strip()[-400:],
            note="framework system check only; NOT a product test")
    except (OSError, subprocess.TimeoutExpired) as exc:
        add("django_system_check", "FAIL", error=type(exc).__name__)


def check_browser():
    try:
        r = run([sys.executable, str(ROOT / "tools" / "browser_smoke.py")], timeout=120, env=tool_env())
        payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
        add("browser_smoke", payload.get("status", "FAIL"),
            channel=payload.get("channel"), steps=payload.get("steps", []),
            screenshot=payload.get("screenshot"), errors=payload.get("error", []),
            download_used=False, exit_code=r.returncode, is_product_test=False)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        add("browser_smoke", "FAIL", error=type(exc).__name__, download_used=False)


def main():
    check_python()
    check_tools()
    check_mysql()
    check_skills()
    check_expert()
    check_plan_rules()
    check_gitignore()
    check_temp_io()
    check_django()
    check_browser()

    core = ["python", "python_imports", "node_pnpm_git", "mysql_service", "mysql_port_3306",
            "skills_both_sides", "plan_rules", "gitignore_secrets", "temp_dir_io",
            "django_system_check", "browser_smoke", "expert_package", "expert_native_validator"]
    core_ok = all(results[k]["status"] == "PASS" for k in core)
    overall = "DEV_TOOLS_READY" if core_ok else "DEV_TOOLS_INCOMPLETE"
    unverified = ["mysql_login", "runtime_ai_connection_test", "expert_gui_visibility", "all_product_tests"]
    add("runtime_ai_policy", "USER_CONNECTS_AT_RUNTIME",
        user_has_api_key=True, developer_needs_key=False, key_received=False)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": "T006",
        "root": str(ROOT),
        "baseline": results["plan_rules"]["plan"] + " (draft) / " + results["plan_rules"]["rules"],
        "overall": overall,
        "not_project_ready": True,
        "scope": "local tooling readiness; zero network, zero product code, no services started",
        "unverified": unverified,
        "checks": results,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"overall: {overall}  (NOT project READY)")
    for key, val in results.items():
        print(f"  {key:<24} {val['status']}")
    print(f"report: {REPORT}")
    return 0 if core_ok else 2


if __name__ == "__main__":
    sys.exit(main())
