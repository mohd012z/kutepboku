"""Read-only health checks for the persistent msasoup host.

Run on the host that owns BOT_DB_PATH, not on an ephemeral GitHub Actions
runner. No session deletion, database creation or automatic VACUUM occurs.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

import requests

MAX_DB_BYTES = 50 * 1024 * 1024
MAX_LOG_BYTES = 20 * 1024 * 1024


def inspect_file(path, limit, *, required):
    file = Path(path)
    if not file.is_file():
        return {"ok": not required, "status": "missing", "size_bytes": None}
    try:
        size = file.stat().st_size
    except OSError:
        return {"ok": False, "status": "unreadable", "size_bytes": None}
    return {"ok": size <= limit, "status": "ok" if size <= limit else "oversize",
            "size_bytes": size}


def inspect_database(path):
    file = Path(path)
    if not file.is_file():
        return {"ok": False, "status": "missing"}
    try:
        # Read-only mode avoids creating an empty database during monitoring.
        with sqlite3.connect(file.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as conn:
            conn.execute("PRAGMA busy_timeout=3000")
            integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                return {"ok": False, "status": "integrity_failed"}
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_sessions'"
            ).fetchone()
            if not table:
                return {"ok": False, "status": "sessions_table_missing"}
            count = conn.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0]
            return {"ok": True, "status": "ok", "session_count": count}
    except (sqlite3.Error, OSError, ValueError):
        return {"ok": False, "status": "database_error"}


def run_health_check(db_path=None, log_path=None):
    db = db_path or os.getenv("BOT_DB_PATH", "bot_sessions.db")
    log = log_path or os.getenv("BOT_LOG_PATH", "logs/bot_errors.log")
    db_file = inspect_file(db, MAX_DB_BYTES, required=True)
    database = inspect_database(db) if db_file["status"] != "missing" else {
        "ok": False, "status": "missing"}
    # File logging is optional: console logging may be the only configured sink.
    log_file = inspect_file(log, MAX_LOG_BYTES, required=False)
    ok = all((db_file["ok"], database["ok"], log_file["ok"]))
    return {"ok": ok, "checked_at": datetime.now(timezone.utc).isoformat(),
            "database_file": db_file, "database": database, "log_file": log_file}


def send_admin_alert(report, *, client=requests, environ=None):
    """Send only generic health statuses; never send file paths or credentials."""
    env = os.environ if environ is None else environ
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("ADMIN_CHAT_ID")
    if not token or not chat_id or report.get("ok"):
        return False
    message = ("msasoup health warning\n"
               "DB file: " + report["database_file"]["status"] + "\n"
               "SQLite: " + report["database"]["status"] + "\n"
               "Log: " + report["log_file"]["status"])
    try:
        response = client.post(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=5)
        response.raise_for_status()
        return response.json().get("ok") is True
    except (requests.RequestException, ValueError, KeyError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="msasoup persistent-host health monitor")
    parser.add_argument("--db", default=None)
    parser.add_argument("--log", default=None)
    parser.add_argument("--alert", action="store_true")
    args = parser.parse_args(argv)
    report = run_health_check(args.db, args.log)
    print(json.dumps(report, sort_keys=True))
    if args.alert and not report["ok"]:
        send_admin_alert(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
