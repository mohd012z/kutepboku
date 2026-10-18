"""Read-only diagnostic snapshot for the running Telegram bot."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import time


def status_snapshot(db_path=None, *, started_at=None, now=None):
    """Report persisted sessions; 'active' means updated within 24 hours."""
    path = Path(db_path if db_path is not None else os.getenv("BOT_DB_PATH", "bot_sessions.db"))
    uptime = max(0, int((now if now is not None else time.monotonic()) - started_at)) if started_at is not None else None
    result = {"exists": path.is_file(), "size_bytes": None, "integrity": "missing",
              "stored_sessions": None, "active_24h": None, "uptime_seconds": uptime}
    if not result["exists"]:
        return result
    try:
        result["size_bytes"] = path.stat().st_size
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            result["integrity"] = "ok" if integrity and integrity[0] == "ok" else "failed"
            if result["integrity"] != "ok":
                return result
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_sessions'").fetchone() is None:
                result["integrity"] = "schema missing"
                return result
            result["stored_sessions"] = conn.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0]
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            result["active_24h"] = conn.execute(
                "SELECT COUNT(*) FROM user_sessions WHERE updated_at >= ?", (cutoff,)
            ).fetchone()[0]
    except (sqlite3.Error, OSError, ValueError):
        result["integrity"] = "unavailable"
    return result


def format_status(info):
    size = "not available" if info["size_bytes"] is None else f'{info["size_bytes"] / 1048576:.2f} MiB'
    uptime = "not measured" if info["uptime_seconds"] is None else f'{info["uptime_seconds"] // 3600}h {(info["uptime_seconds"] % 3600) // 60}m'
    stored = "unknown" if info["stored_sessions"] is None else str(info["stored_sessions"])
    active = "unknown" if info["active_24h"] is None else str(info["active_24h"])
    return ("kutepboku status (current polling process)\n"
            f"Uptime: {uptime}\n"
            f"Database: {'present' if info['exists'] else 'missing'}\n"
            f"Size: {size}\n"
            f"SQLite integrity: {info['integrity']}\n"
            f"Stored sessions: {stored}\n"
            f"Updated in last 24h: {active}")
