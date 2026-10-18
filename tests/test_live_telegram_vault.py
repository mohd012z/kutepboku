"""Opt-in live staging round trip; standard test discovery skips without explicit consent."""
import hashlib
import os
import sqlite3
import tempfile
import unittest
import uuid

from cryptography.fernet import Fernet
from telegram_vault import TelegramVaultClient
from restore_db import restore_snapshot, verify_database_integrity


class LiveTelegramVaultTest(unittest.TestCase):
    def test_round_trip(self):
        if os.getenv("RUN_LIVE_TELEGRAM_TESTS") != "1":
            self.skipTest("Set RUN_LIVE_TELEGRAM_TESTS=1 to enable staging Telegram requests")
        client = TelegramVaultClient()
        message_id = None
        try:
            with tempfile.TemporaryDirectory() as directory:
                source = os.path.join(directory, "source.db")
                with sqlite3.connect(source) as connection:
                    connection.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY, state TEXT)")
                    connection.execute("INSERT INTO user_sessions VALUES (999, 'STAGING_TEST')")
                with sqlite3.connect(source) as connection:
                    baseline_rows = connection.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0]
                    baseline_schema = connection.execute("SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=\'user_sessions\'").fetchone()[0]
                self.assertEqual(baseline_rows, 1)
                self.assertGreater(os.path.getsize(source), 0)
                key = Fernet.generate_key()
                encrypted = os.path.join(directory, "backup.enc")
                with open(source, "rb") as stream:
                    payload = Fernet(key).encrypt(stream.read())
                with open(encrypted, "wb") as stream:
                    stream.write(payload)
                self.assertTrue(os.path.isfile(encrypted))
                self.assertGreater(os.path.getsize(encrypted), 0)
                self.assertFalse(payload.startswith(b"SQLite format 3"))
                original_sha256 = hashlib.sha256(payload).hexdigest()
                # An upload timeout can leave an orphan without a message_id.
                caption = "kutepboku staging " + uuid.uuid4().hex
                result = client.upload_snapshot(encrypted, key, caption)
                message_id = result["message_id"]
                self.assertIsInstance(message_id, int)
                self.assertGreater(message_id, 0)
                self.assertIsInstance(result["file_id"], str)
                self.assertTrue(result["file_id"])
                self.assertEqual(result["file_size"], len(payload))
                self.assertTrue(client.pin_message(message_id), "Staging pin request failed")
                downloaded = os.path.join(directory, "download.enc")
                client.download_file_by_id(result["file_id"], downloaded, expected_size=len(payload),
                                           expected_sha256=original_sha256)
                with open(downloaded, "rb") as stream:
                    self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), original_sha256)
                restored = os.path.join(directory, "restored.db")
                restore_snapshot(downloaded, restored, key)
                self.assertTrue(verify_database_integrity(restored))
                with sqlite3.connect(restored) as connection:
                    self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0], baseline_rows)
                    self.assertEqual(connection.execute("SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=\'user_sessions\'").fetchone()[0], baseline_schema)
                    self.assertEqual(connection.execute("SELECT state FROM user_sessions WHERE user_id=999").fetchone()[0],
                                     "STAGING_TEST")
        finally:
            if message_id is not None:
                # Deleting a channel message does not prove Telegram backend blob erasure.
                self.assertTrue(client.delete_message(message_id), "Staging message cleanup failed; manual investigation required")


if __name__ == "__main__":
    unittest.main()
