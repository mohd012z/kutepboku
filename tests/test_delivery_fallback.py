import smtplib
import unittest
from delivery_fallback import (classify_email_failure, fallback_source_link,
                               send_email_with_fallback)

BOOK = {"title": "Open Book", "source_url": "https://archive.org/download/x/a.pdf",
        "rights_verified": True, "distribution_allowed": True}


class DeliveryFallbackTests(unittest.TestCase):
    def test_valid_source(self):
        self.assertEqual(fallback_source_link(BOOK), BOOK["source_url"])

    def test_unverified_source_rejected(self):
        self.assertIsNone(fallback_source_link({**BOOK, "rights_verified": False}))

    def test_invalid_domain_rejected(self):
        self.assertIsNone(fallback_source_link({**BOOK, "source_url": "https://evil.example/book.pdf"}))

    def test_smtp_timeout_retryable(self):
        self.assertEqual(classify_email_failure(TimeoutError())[0], "SMTP_TRANSIENT")

    def test_auth_error_not_retryable(self):
        self.assertFalse(classify_email_failure(smtplib.SMTPAuthenticationError(535, b"bad"))[1])

    def test_success(self):
        messages = []
        result = send_email_with_fallback(job_id="j1", book=BOOK,
            send_email=lambda: None, notify_user=messages.append,
            telegram_chat_verified=True)
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertFalse(messages)

    def test_failure_fallback(self):
        messages = []
        def fail():
            raise TimeoutError("secret should not appear")
        result = send_email_with_fallback(job_id="j2", book=BOOK,
            send_email=fail, notify_user=messages.append,
            telegram_chat_verified=True)
        self.assertEqual(result["status"], "RETRY_PENDING")
        self.assertIn(BOOK["source_url"], messages[0])
        self.assertNotIn("secret", messages[0])

    def test_unverified_chat_no_link(self):
        messages = []
        result = send_email_with_fallback(job_id="j3", book=BOOK,
            send_email=lambda: (_ for _ in ()).throw(TimeoutError()),
            notify_user=messages.append, telegram_chat_verified=False)
        self.assertFalse(result["fallback_link_offered"])
        self.assertNotIn(BOOK["source_url"], messages[0])

    def test_admin_failure_does_not_mask_email_failure(self):
        def fail():
            raise TimeoutError()
        def admin_fail(_):
            raise RuntimeError()
        result = send_email_with_fallback(job_id="j4", book=BOOK,
            send_email=fail, notify_user=lambda _: None,
            notify_admin=admin_fail, telegram_chat_verified=True)
        self.assertEqual(result["status"], "RETRY_PENDING")


if __name__ == "__main__":
    unittest.main()
