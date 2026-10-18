import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from status_metrics import format_status, status_snapshot


class StatusTests(unittest.TestCase):
    def test_missing_database_does_not_create_file(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "missing.db"
            info = status_snapshot(path, started_at=100, now=161)
            self.assertFalse(path.exists())
            self.assertEqual(info["integrity"], "missing")
            self.assertEqual(info["uptime_seconds"], 61)
            self.assertIn("missing", format_status(info))

    def test_session_counts_and_integrity(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "sessions.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE user_sessions (user_id INTEGER, updated_at TEXT)")
                db.execute("INSERT INTO user_sessions VALUES (1, '2099-01-01T00:00:00+00:00')")
                db.execute("INSERT INTO user_sessions VALUES (2, '2000-01-01T00:00:00+00:00')")
            info = status_snapshot(path, started_at=5, now=65)
            self.assertEqual(info["integrity"], "ok")
            self.assertEqual(info["stored_sessions"], 2)
            self.assertEqual(info["active_24h"], 1)
            self.assertEqual(info["uptime_seconds"], 60)

    def test_missing_schema(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "empty.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE unrelated (id INTEGER)")
            self.assertEqual(status_snapshot(path)["integrity"], "schema missing")
