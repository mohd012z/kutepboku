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


    def test_upload_unconfirmed_does_not_pin(self):
        with TemporaryDirectory() as folder:
            db = Path(folder) / "sessions.db"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY)")
            client = Mock()
            client.post.return_value.json.return_value = {"ok": False}
            with self.assertRaisesRegex(RuntimeError, "upload not confirmed"):
                backup_database_snapshot(db_path=db, token="123:fake", channel_id="-100123",
                    encryption_key=Fernet.generate_key(), client=client)
            self.assertEqual(client.post.call_count, 1)

    def test_uploaded_but_pin_rejected_is_failure(self):
        with TemporaryDirectory() as folder:
            db = Path(folder) / "sessions.db"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY)")
            client = Mock()
            upload = Mock()
            upload.json.return_value = {"ok": True, "result": {"message_id": 42}}
            pin = Mock()
            pin.json.return_value = {"ok": False, "result": False}
            client.post.side_effect = [upload, pin]
            with self.assertRaisesRegex(RuntimeError, "pin was not confirmed"):
                backup_database_snapshot(db_path=db, token="123:fake", channel_id="-100123",
                    encryption_key=Fernet.generate_key(), client=client)
            self.assertEqual(client.post.call_count, 2)

    def test_pin_http_error_is_failure(self):
        with TemporaryDirectory() as folder:
            db = Path(folder) / "sessions.db"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY)")
            client = Mock()
            upload = Mock()
            upload.json.return_value = {"ok": True, "result": {"message_id": 42}}
            pin = Mock()
            from requests import HTTPError
            pin.raise_for_status.side_effect = HTTPError("pin rejected")
            client.post.side_effect = [upload, pin]
            with self.assertRaises(HTTPError):
                backup_database_snapshot(db_path=db, token="123:fake", channel_id="-100123",
                    encryption_key=Fernet.generate_key(), client=client)

