"""Offline SQLite contract checks for the draft Cloudflare D1 webhook schema."""

import sqlite3
import unittest
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "cloudflare"
    / "migrations"
    / "0001_telegram_webhook.sql"
)


class TelegramD1SchemaTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(self.db.close)
        self.sql = MIGRATION.read_text(encoding="utf-8")
        self.db.executescript(self.sql)

    def test_migration_is_repeatable_and_defines_required_columns(self):
        self.db.executescript(self.sql)
        for table, required in {
            "telegram_updates": {"update_id", "status"},
            "telegram_outbox": {
                "id", "update_id", "chat_id", "reply_text", "status", "attempts"
            },
        }.items():
            actual = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
            self.assertTrue(required.issubset(actual), (table, actual))
        self.assertTrue(
            any(row[1] == "idx_telegram_outbox_status"
                for row in self.db.execute("PRAGMA index_list(telegram_outbox)"))
        )

    def test_worker_claim_finalize_and_duplicate_claim(self):
        self.db.execute(
            "INSERT INTO telegram_updates(update_id,status) VALUES (?,'received')", (42,)
        )
        self.db.execute(
            "INSERT INTO telegram_outbox(update_id,chat_id,reply_text,status) "
            "VALUES (?,?,?,'pending')", (42, "123", "Menu")
        )
        claim_sql = (
            "UPDATE telegram_outbox SET status='sending',attempts=attempts+1 "
            "WHERE update_id=? AND status='pending' RETURNING id"
        )
        self.assertIsNotNone(self.db.execute(claim_sql, (42,)).fetchone())
        self.assertIsNone(self.db.execute(claim_sql, (42,)).fetchone())
        self.assertIsNotNone(
            self.db.execute(
                "UPDATE telegram_outbox SET status='sent' "
                "WHERE update_id=? AND status='sending' RETURNING id", (42,)
            ).fetchone()
        )
        self.db.execute("UPDATE telegram_updates SET status='sent' WHERE update_id=?", (42,))
        self.assertEqual(
            self.db.execute(
                "SELECT status, attempts FROM telegram_outbox WHERE update_id=?", (42,)
            ).fetchone(), ("sent", 1)
        )

    def test_rejects_orphan_duplicate_and_invalid_delivery_states(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO telegram_outbox(update_id,chat_id,reply_text,status) "
                "VALUES (?,?,?,'pending')", (99, "123", "Menu")
            )
        self.db.execute("INSERT INTO telegram_updates VALUES (99,'received')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO telegram_updates VALUES (99,'received')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO telegram_outbox(update_id,chat_id,reply_text,status) "
                "VALUES (?,?,?,'retryable')", (99, "123", "Menu")
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO telegram_outbox(update_id,chat_id,reply_text,status,attempts) "
                "VALUES (?,?,?,'pending',-1)", (99, "123", "Menu")
            )

    def test_failed_outbox_insert_rolls_back_inbox_in_one_transaction(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute(
                    "INSERT INTO telegram_updates(update_id,status) VALUES (?,'received')", (100,)
                )
                self.db.execute(
                    "INSERT INTO telegram_outbox(update_id,chat_id,reply_text,status) "
                    "VALUES (?,?,?,'pending')", (100, "", "Menu")
                )
        self.assertIsNone(
            self.db.execute(
                "SELECT update_id FROM telegram_updates WHERE update_id=100"
            ).fetchone()
        )


if __name__ == "__main__":
    unittest.main()
