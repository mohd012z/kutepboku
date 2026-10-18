import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cryptography.fernet import Fernet, InvalidToken
from restore_db import restore_snapshot


class RestoreDatabaseTests(unittest.TestCase):
    def test_restore_valid_encrypted_database(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            original = folder / "original.db"
            with sqlite3.connect(original) as connection:
                connection.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO user_sessions VALUES (123)")
            key = Fernet.generate_key()
            archive = folder / "snapshot.enc"
            archive.write_bytes(Fernet(key).encrypt(original.read_bytes()))
            target = folder / "restored.db"
            restore_snapshot(archive, target, key)
            with sqlite3.connect(target) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("SELECT user_id FROM user_sessions").fetchone()[0], 123)

    def test_corrupt_snapshot_does_not_create_target(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            key = Fernet.generate_key()
            archive = folder / "corrupt.enc"
            archive.write_bytes(Fernet(key).encrypt(b"not a sqlite database"))
            target = folder / "sessions.db"
            with self.assertRaises(sqlite3.DatabaseError):
                restore_snapshot(archive, target, key)
            self.assertFalse(target.exists())

    def test_existing_database_never_overwritten(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            target = folder / "sessions.db"
            target.write_bytes(b"existing sessions")
            archive = folder / "broken.enc"
            archive.write_bytes(b"invalid")
            with self.assertRaises(FileExistsError):
                restore_snapshot(archive, target, Fernet.generate_key())
            self.assertEqual(target.read_bytes(), b"existing sessions")

    def test_invalid_encryption_key_keeps_target_absent(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            archive = folder / "snapshot.enc"
            archive.write_bytes(Fernet(Fernet.generate_key()).encrypt(b"payload"))
            target = folder / "sessions.db"
            with self.assertRaises(InvalidToken):
                restore_snapshot(archive, target, Fernet.generate_key())
            self.assertFalse(target.exists())

    def test_missing_sessions_table_rejected(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            original = folder / "original.db"
            with sqlite3.connect(original) as connection:
                connection.execute("CREATE TABLE other_table (id INTEGER)")
            key = Fernet.generate_key()
            archive = folder / "snapshot.enc"
            archive.write_bytes(Fernet(key).encrypt(original.read_bytes()))
            target = folder / "sessions.db"
            with self.assertRaises(ValueError):
                restore_snapshot(archive, target, key)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
