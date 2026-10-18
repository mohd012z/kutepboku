"""Explicit offline restoration of a Fernet-encrypted SQLite snapshot.

Run with the bot stopped. This tool does not overwrite existing databases.
Telegram download and pinned-message discovery are deliberately separate.
"""
import argparse
from pathlib import Path
import os
import sqlite3
import tempfile

from cryptography.fernet import Fernet


def verify_database_integrity(db_path):
    """Validate an existing SQLite file without creating or modifying it."""
    path = Path(db_path)
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            return db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_sessions'"
            ).fetchone() is not None
    except (sqlite3.Error, OSError, ValueError):
        return False


def restore_snapshot(encrypted_path, target_path, key):
    source = Path(encrypted_path)
    target = Path(target_path)
    if target.exists():
        raise FileExistsError("Target already exists; stop the bot and move the old DB first")
    if not source.is_file():
        raise FileNotFoundError("Encrypted snapshot missing")
    if not key:
        raise ValueError("BACKUP_ENCRYPTION_KEY is required")
    cipher = Fernet(key.encode() if isinstance(key, str) else key)
    with tempfile.TemporaryDirectory(dir=str(target.parent.resolve())) as directory:
        temporary = Path(directory) / "snapshot.db"
        temporary.write_bytes(cipher.decrypt(source.read_bytes()))
        if not verify_database_integrity(temporary):
            raise ValueError("SQLite integrity or required table validation failed")
        os.replace(temporary, target)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--encrypted-file", required=True)
    parser.add_argument("--target", default="bot_sessions.db")
    parser.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()
    if not args.confirm_restore:
        parser.error("Explicit --confirm-restore is required")
    print("Restored:", restore_snapshot(args.encrypted_file, args.target,
                                        os.getenv("BACKUP_ENCRYPTION_KEY")))


if __name__ == "__main__":
    main()
