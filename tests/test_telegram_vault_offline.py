"""Offline regression tests; no live credentials or network required."""
import hashlib
import os
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch

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
        stream = MagicMock()
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


    def test_interrupted_download_sanitizes_error_and_removes_temp(self):
        import requests
        destination = os.path.join(self.temp.name, "download.enc")
        metadata = Mock()
        metadata.json.return_value = {"ok": True, "result": {"file_path": "files/test"}}
        stream = MagicMock()
        stream.iter_content.side_effect = requests.ConnectionError(
            "https://api.telegram.org/file/botstaging/files/test"
        )
        stream.__enter__.return_value = stream
        with patch("telegram_vault.requests.get", side_effect=[metadata, stream]):
            with self.assertRaises(RuntimeError) as raised:
                self.client.download_file_by_id("file-id", destination)
        self.assertNotIn("botstaging", str(raised.exception))
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_cleanup_failure_is_reported_after_publication(self):
        destination = os.path.join(self.temp.name, "download.enc")
        metadata = Mock()
        metadata.json.return_value = {"ok": True, "result": {"file_path": "files/test", "file_size": 4}}
        stream = MagicMock()
        stream.iter_content.return_value = [b"data"]
        stream.__enter__.return_value = stream
        with patch("telegram_vault.requests.get", side_effect=[metadata, stream]), \
             patch("telegram_vault.os.unlink", side_effect=PermissionError("blocked")):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                self.client.download_file_by_id("file-id", destination)
        with open(destination, "rb") as output:
            self.assertEqual(output.read(), b"data")


    def test_upload_malformed_json_is_sanitized(self):
        key = Fernet.generate_key()
        source = os.path.join(self.temp.name, "valid.enc")
        with open(source, "wb") as output:
            output.write(Fernet(key).encrypt(b"test payload"))
        response = Mock()
        response.json.side_effect = ValueError("secret staging token: botstaging")
        with patch("telegram_vault.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Telegram staging API request failed") as raised:
                self.client.upload_snapshot(source, key)
        self.assertNotIn("botstaging", str(raised.exception))

    def test_upload_malformed_result_is_sanitized(self):
        key = Fernet.generate_key()
        source = os.path.join(self.temp.name, "valid.enc")
        with open(source, "wb") as output:
            output.write(Fernet(key).encrypt(b"test payload"))
        with patch.object(self.client, "_api", return_value={"message_id": 1, "document": {}}):
            with self.assertRaisesRegex(RuntimeError, "missing document metadata"):
                self.client.upload_snapshot(source, key)

    def test_partial_stream_interruption_removes_temp(self):
        import requests
        destination = os.path.join(self.temp.name, "partial.enc")
        metadata = Mock()
        metadata.json.return_value = {"ok": True, "result": {"file_path": "documents/snapshot.enc", "file_size": 100}}
        stream = MagicMock()
        def chunks():
            yield b"partial-data"
            raise requests.exceptions.ChunkedEncodingError("botstaging connection broken")
        stream.iter_content.return_value = chunks()
        stream.__enter__.return_value = stream
        with patch("telegram_vault.requests.get", side_effect=[metadata, stream]):
            with self.assertRaisesRegex(RuntimeError, "Telegram staging download failed") as raised:
                self.client.download_file_by_id("file-id", destination, expected_size=100)
        self.assertNotIn("botstaging", str(raised.exception))
        self.assertFalse(os.path.lexists(destination))
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_atomic_link_failure_preserves_destination(self):
        destination = os.path.join(self.temp.name, "download.enc")
        metadata = Mock()
        metadata.json.return_value = {"ok": True, "result": {"file_path": "files/test", "file_size": 4}}
        stream = MagicMock()
        stream.iter_content.return_value = [b"data"]
        stream.__enter__.return_value = stream
        with patch("telegram_vault.requests.get", side_effect=[metadata, stream]), \
             patch("telegram_vault.os.link", side_effect=OSError("permission denied")):
            with self.assertRaisesRegex(RuntimeError, "Atomic no-overwrite publication failed"):
                self.client.download_file_by_id("file-id", destination)
        self.assertFalse(os.path.lexists(destination))
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_download_metadata_invalid_json_is_sanitized(self):
        metadata = Mock()
        metadata.json.side_effect = ValueError("botstaging secret in response")
        with patch("telegram_vault.requests.get", return_value=metadata):
            with self.assertRaisesRegex(RuntimeError, "Telegram file metadata request failed") as raised:
                self.client.download_file_by_id("file-id", os.path.join(self.temp.name, "download.enc"))
        self.assertNotIn("botstaging", str(raised.exception))
        self.assertEqual(os.listdir(self.temp.name), [])


    def test_network_exception_chain_contains_no_staging_token(self):
        import requests
        key = Fernet.generate_key()
        source = os.path.join(self.temp.name, "secret-test.enc")
        with open(source, "wb") as output:
            output.write(Fernet(key).encrypt(b"test payload"))
        secret = "123456789:TEST_SECRET_TOKEN_FOR_EXCEPTION_CHAIN"
        client = TelegramVaultClient(bot_token=secret, channel_id="-1002")
        url = "https://api.telegram.org/bot" + secret + "/sendDocument"
        raw = requests.RequestException("Failed to connect: " + url)
        raw.request = requests.Request("POST", url).prepare()
        with patch("telegram_vault.requests.post", side_effect=raw):
            with self.assertRaises(RuntimeError) as raised:
                client.upload_snapshot(source, key)
        current = raised.exception
        visited = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            self.assertNotIn(secret, repr(current))
            self.assertNotIn(secret, repr(current.args))
            request = getattr(current, "request", None)
            if request is not None:
                self.assertNotIn(secret, str(getattr(request, "url", "")))
            self.assertIsNone(current.__cause__)
            current = current.__context__
        self.assertEqual(len(visited), 1)

    def test_download_exception_chain_contains_no_staging_token(self):
        import requests
        destination = os.path.join(self.temp.name, "secret-download.enc")
        metadata = Mock()
        metadata.json.return_value = {"ok": True, "result": {"file_path": "files/test"}}
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.iter_content.side_effect = requests.ConnectionError(
            "https://api.telegram.org/file/bot" + self.client.bot_token + "/files/test"
        )
        with patch("telegram_vault.requests.get", side_effect=[metadata, stream]):
            with self.assertRaises(RuntimeError) as raised:
                self.client.download_file_by_id("file-id", destination)
        self.assertEqual(str(raised.exception), "Telegram staging download failed")
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(os.path.lexists(destination))
        self.assertEqual(os.listdir(self.temp.name), [])


    def test_missing_staging_credentials_rejected(self):
        with patch.dict(os.environ, {"TELEGRAM_TEST_BOT_TOKEN": "", "TELEGRAM_TEST_CHANNEL_ID": ""}):
            with self.assertRaisesRegex(ValueError, "Dedicated staging"):
                TelegramVaultClient()

    def test_missing_upload_file_rejected(self):
        with self.assertRaises(FileNotFoundError):
            self.client.upload_snapshot(os.path.join(self.temp.name, "missing.enc"), Fernet.generate_key())

    def test_empty_upload_file_rejected(self):
        source = os.path.join(self.temp.name, "empty.enc")
        with open(source, "wb"):
            pass
        with self.assertRaisesRegex(ValueError, "size out of bounds"):
            self.client.upload_snapshot(source, Fernet.generate_key())

    def test_upload_api_rejects_false_ok(self):
        response = Mock()
        response.json.return_value = {"ok": False, "description": "sensitive"}
        with patch("telegram_vault.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "API rejected request"):
                self.client._api("sendDocument")

    def test_upload_api_rejects_non_dict_payload(self):
        response = Mock()
        response.json.return_value = ["unexpected"]
        with patch("telegram_vault.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "API rejected request"):
                self.client._api("sendDocument")

    def test_upload_malformed_metadata_type(self):
        key = Fernet.generate_key()
        source = os.path.join(self.temp.name, "valid-metadata.enc")
        with open(source, "wb") as output:
            output.write(Fernet(key).encrypt(b"test"))
        with patch.object(self.client, "_api", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "missing document metadata"):
                self.client.upload_snapshot(source, key)

    def test_pin_and_delete_false_response(self):
        with patch.object(self.client, "_api", return_value=False):
            self.assertFalse(self.client.pin_message(7))
            self.assertFalse(self.client.delete_message(7))

    def test_metadata_rejected_response(self):
        response = Mock()
        response.json.return_value = {"ok": False}
        with patch("telegram_vault.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "file metadata unavailable"):
                self.client.download_file_by_id("id", os.path.join(self.temp.name, "out.enc"))

    def test_metadata_malformed_result(self):
        response = Mock()
        response.json.return_value = {"ok": True, "result": {}}
        with patch("telegram_vault.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Malformed Telegram file metadata"):
                self.client.download_file_by_id("id", os.path.join(self.temp.name, "out.enc"))

    def test_metadata_path_traversal_rejected(self):
        response = Mock()
        response.json.return_value = {"ok": True, "result": {"file_path": "../secret"}}
        with patch("telegram_vault.requests.get", return_value=response):
            with self.assertRaisesRegex(ValueError, "Invalid Telegram file path"):
                self.client.download_file_by_id("id", os.path.join(self.temp.name, "out.enc"))

    def test_expected_size_out_of_bounds(self):
        with self.assertRaisesRegex(ValueError, "Expected size out of bounds"):
            self.client.download_file_by_id("id", os.path.join(self.temp.name, "out.enc"), expected_size=0)

    def test_server_size_out_of_bounds(self):
        response = Mock()
        response.json.return_value = {"ok": True, "result": {"file_path": "files/a", "file_size": 0}}
        with patch("telegram_vault.requests.get", return_value=response):
            with self.assertRaisesRegex(ValueError, "Telegram file size out of bounds"):
                self.client.download_file_by_id("id", os.path.join(self.temp.name, "out.enc"))

    def test_empty_download_rejected(self):
        with self.assertRaisesRegex(ValueError, "Downloaded snapshot size mismatch"):
            self._download([])

    def test_existing_destination_created_during_publication(self):
        destination = os.path.join(self.temp.name, "download.enc")
        metadata = Mock()
        metadata.json.return_value = {"ok": True, "result": {"file_path": "files/test"}}
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.iter_content.return_value = [b"data"]
        def competing_writer(source, target):
            with open(target, "wb") as output:
                output.write(b"other")
            raise FileExistsError("already created")
        with patch("telegram_vault.requests.get", side_effect=[metadata, stream]), \
             patch("telegram_vault.os.link", side_effect=competing_writer):
            with self.assertRaisesRegex(FileExistsError, "Download destination exists"):
                self.client.download_file_by_id("id", destination)
        with open(destination, "rb") as stream:
            self.assertEqual(stream.read(), b"other")

if __name__ == "__main__":
    unittest.main()
