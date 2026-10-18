"""Staging-only Telegram encrypted snapshot transport; never uses production credentials."""
import hashlib
import logging
import os
import tempfile

import requests
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)
MAX_SNAPSHOT_SIZE = 50 * 1024 * 1024


class TelegramVaultClient:
    def __init__(self, bot_token=None, channel_id=None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_TEST_BOT_TOKEN")
        self.channel_id = channel_id or os.getenv("TELEGRAM_TEST_CHANNEL_ID")
        if not self.bot_token or not self.channel_id:
            raise ValueError("Dedicated staging bot token and channel ID are required")
        if self.bot_token == os.getenv("TELEGRAM_BOT_TOKEN") or str(self.channel_id) == os.getenv("TELEGRAM_BACKUP_CHANNEL_ID"):
            raise ValueError("Staging credentials must differ from production")
        self.base_url = "https://api.telegram.org/bot" + self.bot_token

    def _api(self, method, *, data=None, files=None):
        failed = False
        try:
            response = requests.post(self.base_url + "/" + method, data=data, files=files, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            failed = True
        if failed:
            raise RuntimeError("Telegram staging API request failed")
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("Telegram staging API rejected request")
        return payload.get("result")

    def upload_snapshot(self, file_path, encryption_key, caption="kutepboku staging vault test"):
        if not os.path.isfile(file_path):
            raise FileNotFoundError("Encrypted snapshot missing")
        size = os.path.getsize(file_path)
        if not 0 < size <= MAX_SNAPSHOT_SIZE:
            raise ValueError("Snapshot size out of bounds")
        try:
            with open(file_path, "rb") as stream:
                token = stream.read(MAX_SNAPSHOT_SIZE + 1)
            Fernet(encryption_key).decrypt(token)
        except (InvalidToken, ValueError, TypeError):
            raise ValueError("Snapshot authentication failed") from None
        if len(token) != size:
            raise ValueError("Snapshot changed during validation")
        # A network timeout after Telegram accepts the upload can leave an orphan.
        with open(file_path, "rb") as stream:
            result = self._api("sendDocument", data={"chat_id": self.channel_id, "caption": caption},
                               files={"document": stream})
        try:
            return {"message_id": result["message_id"], "file_id": result["document"]["file_id"],
                    "file_size": result["document"]["file_size"]}
        except (KeyError, TypeError):
            raise RuntimeError("Telegram upload response missing document metadata") from None

    def pin_message(self, message_id):
        return self._api("pinChatMessage", data={"chat_id": self.channel_id, "message_id": message_id}) is True

    def delete_message(self, message_id):
        return self._api("deleteMessage", data={"chat_id": self.channel_id, "message_id": message_id}) is True

    def download_file_by_id(self, file_id, destination_path, expected_size=None, expected_sha256=None):
        if os.path.lexists(destination_path):
            raise FileExistsError("Download destination exists")
        if expected_size is not None and not 0 < expected_size <= MAX_SNAPSHOT_SIZE:
            raise ValueError("Expected size out of bounds")
        failed = False
        try:
            response = requests.get(self.base_url + "/getFile", params={"file_id": file_id}, timeout=15)
            response.raise_for_status()
            metadata = response.json()
        except (requests.RequestException, ValueError):
            failed = True
        if failed:
            raise RuntimeError("Telegram file metadata request failed")
        if not isinstance(metadata, dict) or metadata.get("ok") is not True:
            raise RuntimeError("Telegram file metadata unavailable")
        try:
            info = metadata["result"]
            server_size = info.get("file_size")
            server_path = info["file_path"]
            if not isinstance(server_path, str) or not server_path or server_path.startswith("/") or ".." in server_path.split("/"):
                raise ValueError("Invalid Telegram file path")
            if server_size is not None and not 0 < server_size <= MAX_SNAPSHOT_SIZE:
                raise ValueError("Telegram file size out of bounds")
        except (KeyError, TypeError):
            raise RuntimeError("Malformed Telegram file metadata") from None
        if expected_size is not None and server_size is not None and expected_size != server_size:
            raise ValueError("Telegram file size mismatch")
        directory = os.path.dirname(os.path.abspath(destination_path))
        fd, temp_path = tempfile.mkstemp(prefix="vault_dl_", dir=directory)
        digest = hashlib.sha256()
        total = 0
        try:
            with os.fdopen(fd, "wb") as output:
                download_failed = False
                try:
                    with requests.get("https://api.telegram.org/file/bot" + self.bot_token + "/" + server_path,
                                      stream=True, timeout=45) as download:
                        download.raise_for_status()
                        for chunk in download.iter_content(chunk_size=8192):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > MAX_SNAPSHOT_SIZE:
                                raise ValueError("Telegram download exceeds size limit")
                            output.write(chunk)
                            digest.update(chunk)
                except requests.RequestException:
                    download_failed = True
                if download_failed:
                    raise RuntimeError("Telegram staging download failed")
                output.flush()
                os.fsync(output.fileno())
            if not total or (server_size is not None and total != server_size) or (expected_size is not None and total != expected_size):
                raise ValueError("Downloaded snapshot size mismatch")
            if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
                raise ValueError("Downloaded snapshot SHA-256 mismatch")
            try:
                os.link(temp_path, destination_path)
            except FileExistsError:
                raise FileExistsError("Download destination exists") from None
            except OSError:
                raise RuntimeError("Atomic no-overwrite publication failed") from None
            return destination_path
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                logger.error("Staging download temporary-file cleanup failed")
                raise RuntimeError("Staging download temporary-file cleanup failed") from None
