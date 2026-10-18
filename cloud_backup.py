"""Encrypted SQLite snapshot upload to a private Telegram channel.

No database contents are logged. Requires a dedicated Fernet key and admin channel.
"""
import os
from pathlib import Path
import sqlite3
import tempfile

from cryptography.fernet import Fernet
import requests

from restore_db import verify_database_integrity


def backup_database_snapshot(*, db_path=None, token=None, channel_id=None,
                             encryption_key=None, client=None):
    """Return Telegram message ID only after upload AND pin are confirmed.

    The snapshot is consistent even when SQLite WAL mode is in use.
    Failure to pin raises an exception; the uploaded document may still exist.
    """
    path = Path(db_path or os.getenv("BOT_DB_PATH", "bot_sessions.db"))
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = channel_id or os.getenv("TELEGRAM_BACKUP_CHANNEL_ID")
    encryption_key = encryption_key or os.getenv("BACKUP_ENCRYPTION_KEY")
    if not token or not channel_id or not encryption_key:
        raise ValueError("Telegram token, backup channel and encryption key are required")
    if not path.is_file():
        raise FileNotFoundError("Session database not found")
    cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
    client = client or requests.Session()
    with tempfile.TemporaryDirectory() as folder:
        snapshot = Path(folder) / "snapshot.db"
        source_uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=10) as source:
            with sqlite3.connect(snapshot) as destination:
                source.backup(destination)
        if not verify_database_integrity(snapshot):
            raise ValueError("Snapshot failed SQLite integrity validation")
        encrypted = cipher.encrypt(snapshot.read_bytes())
        endpoint = "https://api.telegram.org/bot" + token
        response = client.post(
            endpoint + "/sendDocument",
            data={"chat_id": channel_id, "disable_notification": "true"},
            files={"document": ("sessions.snapshot.enc", encrypted, "application/octet-stream")},
            timeout=(10, 60),
        )
        response.raise_for_status()
        payload = response.json()
        message_id = (payload.get("result") or {}).get("message_id") if payload.get("ok") is True else None
        if not isinstance(message_id, int):
            raise RuntimeError("Telegram backup upload not confirmed")
        pinned = client.post(
            endpoint + "/pinChatMessage",
            data={"chat_id": channel_id, "message_id": message_id,
                  "disable_notification": "true"},
            timeout=(10, 20),
        )
        pinned.raise_for_status()
        if pinned.json().get("ok") is not True or pinned.json().get("result") is not True:
            raise RuntimeError("Snapshot uploaded but Telegram pin was not confirmed")
        return message_id
