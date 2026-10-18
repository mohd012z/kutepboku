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
                key = Fernet.generate_key()
                encrypted = os.path.join(directory, "backup.enc")
                with open(source, "rb") as stream:
                    payload = Fernet(key).encrypt(stream.read())
                with open(encrypted, "wb") as stream:
                    stream.write(payload)
                # An upload timeout can leave an orphan without a message_id.
                caption = "kutepboku staging " + uuid.uuid4().hex
                result = client.upload_snapshot(encrypted, key, caption)
                message_id = result["message_id"]
                self.assertTrue(client.pin_message(message_id), "Staging pin request failed")
                downloaded = os.path.join(directory, "download.enc")
                client.download_file_by_id(result["file_id"], downloaded, expected_size=len(payload),
                                           expected_sha256=hashlib.sha256(payload).hexdigest())
                restored = os.path.join(directory, "restored.db")
                restore_snapshot(downloaded, restored, key)
                self.assertTrue(verify_database_integrity(restored))
                with sqlite3.connect(restored) as connection:
                    self.assertEqual(connection.execute("SELECT state FROM user_sessions WHERE user_id=999").fetchone()[0],
                                     "STAGING_TEST")
        finally:
            if message_id is not None:
                self.assertTrue(client.delete_message(message_id), "Staging message cleanup failed")


if __name__ == "__main__":
    unittest.main()
