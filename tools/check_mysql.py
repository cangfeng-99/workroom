"""Local MySQL connectivity check (no schema, no account changes, no secret storage).

Password is read with getpass (hidden, typed by the user in their own terminal).
It is never printed, logged, written to disk, or passed on a command line.
Only loopback targets are accepted. This verifies a local login; it does NOT
configure or persist anything.
"""

import argparse
import getpass
import json
import sys
from datetime import datetime
from pathlib import Path

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
MAX_TIMEOUT = 5
CODES = {
    "CONNECTED": 0,
    "NOT_CONFIGURED": 3,
    "ACCESS_DENIED": 10,
    "UNKNOWN_DATABASE": 11,
    "CANNOT_CONNECT": 12,
    "TIMEOUT": 13,
    "DRIVER_MISSING": 14,
    "BAD_ARGS": 15,
}


def emit(result: dict, report: Path | None) -> int:
    payload = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": result["status"],
        "code": result["code"],
        "host": result.get("host"),
        "port": result.get("port"),
        "server_version": result.get("server_version"),
        "detail": result.get("detail"),
        "password_stored": False,
        "user_recorded": False,
        "schema_changed": False,
        "note": "local login check only; nothing was configured or persisted",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return CODES[result["code"]]


def classify(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc).lower()
    if "timed out" in text or "timeout" in text or "timeout" in name.lower():
        return "TIMEOUT"
    if "access denied" in text or name == "OperationalError" and "1045" in text:
        return "ACCESS_DENIED"
    if "unknown database" in text or "1049" in text:
        return "UNKNOWN_DATABASE"
    return "CANNOT_CONNECT"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check a LOCAL MySQL login (loopback only). No database is created, "
                    "no account is modified, and no password is stored."
    )
    ap.add_argument("--user", help="MySQL user name (asked interactively if omitted)")
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 or localhost only")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--database", default=None, help="optional database name to select")
    ap.add_argument("--report", default=None, help="optional JSON report path (never contains user/password)")
    ap.add_argument("--timeout", type=int, default=MAX_TIMEOUT, help="connect timeout, capped at 5s")
    args = ap.parse_args()

    report = Path(args.report).resolve() if args.report else None
    if args.host not in ALLOWED_HOSTS:
        return emit({"status": "FAIL", "code": "BAD_ARGS",
                     "detail": "host must be 127.0.0.1 or localhost"}, report)
    timeout = max(1, min(args.timeout, MAX_TIMEOUT))

    user = args.user
    if not user:
        try:
            user = input("MySQL user: ").strip()
        except EOFError:
            user = ""
    if not user:
        return emit({"status": "NOT_CONFIGURED", "code": "NOT_CONFIGURED",
                     "host": args.host, "port": args.port,
                     "detail": "no user name provided; nothing attempted"}, report)

    try:
        import MySQLdb
    except ImportError:
        return emit({"status": "FAIL", "code": "DRIVER_MISSING",
                     "detail": "mysqlclient (MySQLdb) is not importable in this interpreter"}, report)

    try:
        password = getpass.getpass("MySQL password (hidden, not stored): ")
    except (EOFError, KeyboardInterrupt):
        return emit({"status": "NOT_CONFIGURED", "code": "NOT_CONFIGURED",
                     "host": args.host, "port": args.port,
                     "detail": "no password entered; no login retried or guessed"}, report)

    if not password:
        return emit({"status": "NOT_CONFIGURED", "code": "NOT_CONFIGURED",
                     "host": args.host, "port": args.port,
                     "detail": "empty password not attempted; nothing guessed"}, report)

    try:
        conn = MySQLdb.connect(
            host=args.host, port=args.port, user=user, passwd=password,
            db=args.database or None, connect_timeout=timeout, charset="utf8mb4",
        )
    except MySQLdb.Error as exc:
        code = classify(exc)
        detail = {
            "ACCESS_DENIED": "server rejected the credentials (access denied)",
            "UNKNOWN_DATABASE": "credentials accepted but the database name does not exist",
            "TIMEOUT": "connection timed out",
            "CANNOT_CONNECT": "could not connect to the local server",
        }[code]
        return emit({"status": "FAIL", "code": code, "host": args.host,
                     "port": args.port, "detail": detail}, report)
    finally:
        password = None

    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        row = cur.fetchone()
        if not row or row[0] != 1:
            raise RuntimeError("SELECT 1 returned an unexpected result")
        cur.execute("SELECT VERSION()")
        version = str(cur.fetchone()[0])
        cur.close()
    except (MySQLdb.Error, RuntimeError, TypeError, IndexError):
        return emit({"status": "FAIL", "code": "CANNOT_CONNECT", "host": args.host,
                     "port": args.port, "detail": "connected but the verification query failed"}, report)
    finally:
        conn.close()

    return emit({"status": "CONNECTED", "code": "CONNECTED", "host": args.host,
                 "port": args.port, "server_version": version,
                 "detail": "login verified with SELECT 1 and VERSION()"}, report)


if __name__ == "__main__":
    sys.exit(main())
