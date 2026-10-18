"""Offline regression tests; no live credentials or network required."""
import hashlib
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from telegram_vault import TelegramVaultClient


class VaultOfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "production", "TELEGRAM_BACKUP_CHANNEL_ID": "-1001"}):
            self.client = TelegramVaultClient(bot_token="staging", channel_id="-1002")

    def test_rejects_production_token(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "production"}):
            with self.assertRaises(ValueError):
                TelegramVaultClient(bot_token="production", channel_id="-1002")

    def test_rejects_production_channel(self):
        with patch.dict(os.environ, {"TELEGRAM_BACKUP_CHANNEL_ID": "-1001"}):
            with self.assertRaises(ValueError):
                TelegramVaultClient(bot_token="staging", channel_id="-1001")

    def test_rejects_invalid_encryption(self):
        path = os.path.join(self.temp.name, "bad.enc")
        with open(path, "wb") as output:
            output.write(b"plaintext")
        with self.assertRaises(ValueError):
            self.client.upload_snapshot(path, Fernet.generate_key())

    def test_valid_upload_and_metadata(self):
        key = Fernet.generate_key()
        path = os.path.join(self.temp.name, "snapshot.enc")
        with open(path, "wb") as output:
            output.write(Fernet(key).encrypt(b"test"))
        with patch.object(self.client, "_api", return_value={"message_id": 7, "document": {"file_id": "abc", "file_size": 100}}):
            result = self.client.upload_snapshot(path, key)
        self.assertEqual(result["file_id"], "abc")

    def _download(self, chunks, *, reported=None, expected=None, digest=None):
        destination = os.path.join(self.temp.name, "download.enc")
        metadata = Mock()
        metadata.json.return_value = {"ok": True, "result": {"file_path": "files/test", "file_size": reported}}
        stream = Mock()
        stream.iter_content.return_value = chunks
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        with patch("telegram_vault.requests.get", side_effect=[metadata, stream]):
            return self.client.download_file_by_id("file-id", destination, expected_size=expected, expected_sha256=digest)

    def test_download_verified(self):
        data = b"encrypted-data"
        result = self._download([data], reported=len(data), expected=len(data), digest=hashlib.sha256(data).hexdigest())
        with open(result, "rb") as stream:
            self.assertEqual(stream.read(), data)

    def test_download_rejects_expected_size_mismatch(self):
        with self.assertRaises(ValueError):
            self._download([b"short"], expected=100)
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_download_rejects_hash_mismatch(self):
        with self.assertRaises(ValueError):
            self._download([b"data"], digest="0" * 64)
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_existing_destination_preserved(self):
        destination = os.path.join(self.temp.name, "download.enc")
        with open(destination, "wb") as output:
            output.write(b"existing")
        with self.assertRaises(FileExistsError):
            self.client.download_file_by_id("file-id", destination)
        with open(destination, "rb") as stream:
            self.assertEqual(stream.read(), b"existing")

    def test_network_failure_does_not_expose_token(self):
        import requests
        with patch("telegram_vault.requests.get", side_effect=requests.RequestException("https://api.telegram.org/botstaging/getFile")):
            with self.assertRaises(RuntimeError) as raised:
                self.client.download_file_by_id("id", os.path.join(self.temp.name, "new"))
        self.assertNotIn("botstaging", str(raised.exception))

    def test_oversized_stream_is_rejected(self):
        import telegram_vault
        with patch.object(telegram_vault, "MAX_SNAPSHOT_SIZE", 4):
            with self.assertRaises(ValueError):
                self._download([b"too-large"])
        self.assertEqual(os.listdir(self.temp.name), [])


if __name__ == "__main__":
    unittest.main()
