import unittest
from unittest.mock import Mock
from whatsapp_gateway import DeliveryRequest, deliver_document, normalize_phone, share_link
from telegram_whatsapp import authorized_user, book_keyboard, process_callback


class WhatsAppTests(unittest.TestCase):
    def test_share_link(self):
        url = share_link("Python Basics", "https://archive.org/details/example")
        self.assertTrue(url.startswith("https://wa.me/?text="))
        self.assertIn("Python+Basics", url)

    def test_reject_unapproved_link(self):
        with self.assertRaises(ValueError):
            share_link("Book", "https://private.example/file.pdf")

    def test_phone_validation(self):
        self.assertEqual(normalize_phone("+60 12-345 6789"), "60123456789")
        with self.assertRaises(ValueError):
            normalize_phone("012345")

    def test_keyboard(self):
        keyboard = book_keyboard("bk_1", "Example", "https://openlibrary.org/works/OL1W")
        self.assertEqual(keyboard["inline_keyboard"][2][0]["callback_data"], "wa:bk_1")

    def test_authorization_denies_by_default(self):
        self.assertFalse(authorized_user(42, environ={}))

    def test_authorization_allows_listed_user(self):
        self.assertTrue(authorized_user(42, environ={"TELEGRAM_ALLOWED_USER_IDS": "42, 7"}))

    def test_callback_rejects_unknown_user(self):
        result = process_callback({"from": {"id": 12}, "data": "wa:bk_1"},
                                  book_lookup=lambda key: {}, request_store=lambda *a: "1",
                                  environ={"TELEGRAM_ALLOWED_USER_IDS": "42"})
        self.assertFalse(result["ok"])

    def test_callback_creates_pending_request_only(self):
        saved = []
        result = process_callback({"from": {"id": 42}, "data": "wa:bk_1"},
                                  book_lookup=lambda key: {"source_url": "https://archive.org/details/example"},
                                  request_store=lambda *args: saved.append(args) or "req1",
                                  environ={"TELEGRAM_ALLOWED_USER_IDS": "42"})
        self.assertTrue(result["ok"])
        self.assertEqual(saved, [(42, "bk_1")])

    def test_auto_delivery_disabled(self):
        req = DeliveryRequest("book1", "Book", "60123456789",
                              "https://archive.org/details/example", True, True)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            deliver_document(req, environ={})

    def test_consent_required(self):
        req = DeliveryRequest("book1", "Book", "60123456789",
                              "https://archive.org/details/example", False, True)
        with self.assertRaises(PermissionError):
            deliver_document(req, environ={})

    def test_confirmation_required(self):
        req = DeliveryRequest("book1", "Book", "60123456789",
                              "https://archive.org/details/example", True, False)
        with self.assertRaises(PermissionError):
            deliver_document(req, environ={})

    def test_api_success(self):
        req = DeliveryRequest("book1", "Book", "60123456789",
                              "https://archive.org/details/example", True, True)
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"messages": [{"id": "wamid.test"}]}
        result = deliver_document(req, session=session, environ={
            "WHATSAPP_DELIVERY_ENABLED": "true", "WHATSAPP_ACCESS_TOKEN": "secret",
            "WHATSAPP_PHONE_NUMBER_ID": "123456789", "WHATSAPP_GRAPH_VERSION": "v23.0"})
        self.assertEqual(result, "wamid.test")
        self.assertEqual(session.post.call_args.kwargs["json"]["type"], "document")


if __name__ == "__main__":
    unittest.main()
