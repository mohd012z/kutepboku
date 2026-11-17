"""Offline recovery safety drill: never access the repository's live database."""
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.fernet import Fernet, InvalidToken

from restore_db import restore_snapshot, verify_database_integrity


class RecoveryDrillTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.original = self.folder / "known_good.db"
        self.target = self.folder / "restored.db"
        self.encrypted = self.folder / "snapshot.enc"
        self.key = Fernet.generate_key()
        with sqlite3.connect(self.original) as db:
            db.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY, state TEXT)")
            db.execute("INSERT INTO user_sessions VALUES (1, 'KNOWN_GOOD_STATE')")
        self.original_bytes = self.original.read_bytes()
        self.encrypted.write_bytes(Fernet(self.key).encrypt(self.original_bytes))

    def assert_known_good(self, path):
        self.assertTrue(verify_database_integrity(path))
        with sqlite3.connect(path) as db:
            self.assertEqual(
                db.execute("SELECT state FROM user_sessions WHERE user_id=1").fetchone()[0],
                "KNOWN_GOOD_STATE",
            )

    def assert_source_preserved(self):
        self.assertEqual(self.original.read_bytes(), self.original_bytes)
        self.assert_known_good(self.original)

    def test_valid_restore_into_absent_target(self):
        self.assertEqual(restore_snapshot(self.encrypted, self.target, self.key), self.target)
        self.assert_known_good(self.target)
        self.assert_source_preserved()

    def test_truncated_encrypted_snapshot_rejected(self):
        self.encrypted.write_bytes(self.encrypted.read_bytes()[:24])
        with self.assertRaises(InvalidToken):
            restore_snapshot(self.encrypted, self.target, self.key)
        self.assertFalse(self.target.exists())
        self.assert_source_preserved()

    def test_wrong_fernet_key_rejected(self):
        with self.assertRaises(InvalidToken):
            restore_snapshot(self.encrypted, self.target, Fernet.generate_key())
        self.assertFalse(self.target.exists())
        self.assert_source_preserved()

    def test_atomic_rename_failure_leaves_no_target(self):
        with patch("restore_db.os.replace", side_effect=OSError("simulated disk failure")) as swap:
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                restore_snapshot(self.encrypted, self.target, self.key)
            swap.assert_called_once()
        self.assertFalse(self.target.exists())
        self.assert_source_preserved()
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["known_good.db", "snapshot.enc"])

    def test_existing_target_rejected_even_with_active_writer(self):
        with sqlite3.connect(self.target) as db:
            db.execute("CREATE TABLE user_sessions (user_id INTEGER PRIMARY KEY, state TEXT)")
            db.execute("INSERT INTO user_sessions VALUES (99, 'ACTIVE_STATE')")
        before = self.target.read_bytes()
        writer = sqlite3.connect(self.target, timeout=1)
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE user_sessions SET state='ACTIVE_STATE' WHERE user_id=99")
            with self.assertRaises(FileExistsError):
                restore_snapshot(self.encrypted, self.target, self.key)
            self.assertEqual(self.target.read_bytes(), before)
            with sqlite3.connect(self.target) as reader:
                # The writer's uncommitted change is not required for this assertion.
                self.assertEqual(reader.execute("SELECT state FROM user_sessions WHERE user_id=99").fetchone()[0],
                                 "ACTIVE_STATE")
        finally:
            writer.rollback()
            writer.close()
        self.assert_source_preserved()


if __name__ == "__main__":
    unittest.main()
