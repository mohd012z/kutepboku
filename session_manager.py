"""SQLite-backed Telegram FSM sessions. Keep database on persistent storage."""
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


class SessionManager:
    def __init__(self, db_path="bot_sessions.db"):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def get_session(self, user_id):
        with self._connect() as conn:
            row = conn.execute("SELECT state, data FROM user_sessions WHERE user_id=?",
                               (int(user_id),)).fetchone()
        return (row[0], json.loads(row[1])) if row else ("IDLE", {})

    def set_session(self, user_id, state, data):
        payload = json.dumps(data, ensure_ascii=False)
        stamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("""INSERT INTO user_sessions (user_id,state,data,updated_at)
                VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                state=excluded.state,data=excluded.data,updated_at=excluded.updated_at""",
                (int(user_id), str(state), payload, stamp))

    def clear_session(self, user_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM user_sessions WHERE user_id=?", (int(user_id),))
