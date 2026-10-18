import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from health_check import inspect_database, inspect_file, run_health_check, send_admin_alert


class HealthCheckTests(unittest.TestCase):
    def test_missing_db_fails(self):
        with TemporaryDirectory() as d:
            report = run_health_check(str(Path(d) / "missing.db"),
                                      str(Path(d) / "missing.log"))
            self.assertFalse(report["ok"])
            self.assertEqual(report["database"]["status"], "missing")

    def test_valid_db(self):
        with TemporaryDirectory() as d:
            db = Path(d) / "sessions.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY)")
                conn.execute("INSERT INTO user_sessions VALUES (1)")
            result = inspect_database(str(db))
            self.assertTrue(result["ok"])
            self.assertEqual(result["session_count"], 1)

    def test_missing_table(self):
        with TemporaryDirectory() as d:
            db = Path(d) / "sessions.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE unrelated (id INTEGER)")
            self.assertEqual(inspect_database(str(db))["status"], "sessions_table_missing")

    def test_corrupt_db(self):
        with TemporaryDirectory() as d:
            db = Path(d) / "sessions.db"
            db.write_bytes(b"not sqlite")
            self.assertFalse(inspect_database(str(db))["ok"])

    def test_log_optional(self):
        with TemporaryDirectory() as d:
            self.assertTrue(inspect_file(str(Path(d) / "missing.log"), 100,
                                         required=False)["ok"])

    def test_oversize_file(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "log"
            path.write_bytes(b"012345")
            self.assertEqual(inspect_file(str(path), 5, required=True)["status"], "oversize")

    def test_no_alert_when_healthy(self):
        client = Mock()
        self.assertFalse(send_admin_alert({"ok": True}, client=client,
            environ={"TELEGRAM_BOT_TOKEN": "token", "ADMIN_CHAT_ID": "42"}))
        client.post.assert_not_called()

    def test_alert_redacts_paths(self):
        client = Mock()
        client.post.return_value.json.return_value = {"ok": True}
        report = {"ok": False, "database_file": {"status": "oversize"},
                  "database": {"status": "database_error"},
                  "log_file": {"status": "ok"}}
        self.assertTrue(send_admin_alert(report, client=client,
            environ={"TELEGRAM_BOT_TOKEN": "token", "ADMIN_CHAT_ID": "42"}))
        message = client.post.call_args.kwargs["json"]["text"]
        self.assertNotIn("token", message)


if __name__ == "__main__":
    unittest.main()
