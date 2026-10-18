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
        with sqlite3.connect(temporary.resolve().as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_sessions'").fetchone():
                raise ValueError("Required user_sessions table missing")
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
