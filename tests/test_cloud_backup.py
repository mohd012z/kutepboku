import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from cryptography.fernet import Fernet
from cloud_backup import backup_database_snapshot


class BackupTests(unittest.TestCase):
    def test_missing_config_rejected(self):
        with self.assertRaises(ValueError):
            backup_database_snapshot(db_path="/nonexistent", token="", channel_id="",
                                     encryption_key="", client=Mock())

    def test_upload_and_pin(self):
        with TemporaryDirectory() as folder:
            db = Path(folder) / "sessions.db"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY)")
            client = Mock()
            upload = Mock()
            upload.json.return_value = {"ok": True, "result": {"message_id": 42}}
            pin = Mock()
            pin.json.return_value = {"ok": True, "result": True}
            client.post.side_effect = [upload, pin]
            result = backup_database_snapshot(db_path=db, token="123:fake",
                channel_id="-100123", encryption_key=(client_key := Fernet.generate_key()), client=client)
            self.assertEqual(result, 42)
            self.assertEqual(client.post.call_count, 2)
            encrypted = client.post.call_args_list[0].kwargs["files"]["document"][1]
            self.assertTrue(Fernet(client_key).decrypt(encrypted).startswith(b"SQLite format 3"))
