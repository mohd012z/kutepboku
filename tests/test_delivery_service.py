import os
from pathlib import Path
import unittest
from unittest.mock import Mock

from delivery_service import dispatch, temporary_book, validate_file

BOOK = {"title": "Python", "source_url": "https://archive.org/download/x/a.pdf",
        "rights_verified": True, "distribution_allowed": True}


def downloader(url, path, max_bytes):
    Path(path).write_bytes(b"%PDF-1.7\n" + b"sample" * 50)


class DeliveryTests(unittest.TestCase):
    def test_unverified_rights_denied(self):
        with self.assertRaises(PermissionError):
            dispatch({"title": "x", "source_url": BOOK["source_url"]},
                     "whatsapp_share", sender_confirmed=True)

    def test_sender_confirmation_required(self):
        with self.assertRaises(PermissionError):
            dispatch(BOOK, "whatsapp_share")

    def test_share_without_download(self):
        result = dispatch(BOOK, "whatsapp_share", sender_confirmed=True)
        self.assertEqual(result["status"], "SHARE_READY")
        self.assertIn("wa.me", result["url"])

    def test_recipient_verification_required(self):
        with self.assertRaises(PermissionError):
            dispatch(BOOK, "telegram", sender_confirmed=True, downloader=downloader)

    def test_cleanup_after_success(self):
        with temporary_book(BOOK, downloader=downloader) as (path, mime, filename):
            self.assertTrue(os.path.exists(path))
            self.assertEqual(mime, "application/pdf")
        self.assertFalse(os.path.exists(path))

    def test_cleanup_after_exception(self):
        try:
            with temporary_book(BOOK, downloader=downloader) as (path, _, _):
                raise RuntimeError("stop")
        except RuntimeError:
            pass
        self.assertFalse(os.path.exists(path))

    def test_reject_invalid_document(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            p = Path(d) / "invalid"
            p.write_bytes(b"not a book")
            with self.assertRaises(ValueError):
                validate_file(p)

    def test_telegram_delivery(self):
        client = Mock()
        client.post.return_value.json.return_value = {
            "ok": True, "result": {"message_id": 17}}
        result = dispatch(BOOK, "telegram", downloader=downloader,
                          telegram_chat=42, recipient_verified=True,
                          sender_confirmed=True, telegram_client=client,
                          environ={"TELEGRAM_BOT_TOKEN": "testtoken"})
        self.assertEqual(result["message_id"], 17)

    def test_missing_smtp_configuration(self):
        with self.assertRaises(RuntimeError):
            dispatch(BOOK, "email", recipient="verified@example.org",
                     downloader=downloader, recipient_verified=True,
                     sender_confirmed=True, environ={})


if __name__ == "__main__":
    unittest.main()
