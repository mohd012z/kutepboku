import unittest
from delivery_ui import menu, book_card, destination_menu, confirmation, route_callback


BOOK = {"title": "Example", "author": "Writer",
        "source_url": "https://archive.org/details/example"}


class DeliveryUITests(unittest.TestCase):
    def test_menu(self):
        self.assertEqual(len(menu()["reply_markup"]["inline_keyboard"]), 3)

    def test_book_card(self):
        self.assertIn("Send / Share", str(book_card("b1", **BOOK)))

    def test_destination_options(self):
        keyboard = destination_menu("b1", BOOK["title"], BOOK["source_url"])
        text = str(keyboard)
        for name in ("Telegram", "Email", "WhatsApp"):
            self.assertIn(name, text)

    def test_reject_unsafe_source(self):
        with self.assertRaises(ValueError):
            destination_menu("b1", "Example", "https://internal.example/test")

    def test_confirmation(self):
        self.assertIn("verified email", confirmation("b1", "email")["text"])

    def test_denied(self):
        response = route_callback({"from": {"id": 3}, "data": "ui:deliver:b1"},
                                  book_lookup=lambda _: BOOK, enqueue_request=lambda *args: 1,
                                  environ={"TELEGRAM_ALLOWED_USER_IDS": "5"})
        self.assertIn("denied", response["text"])

    def test_confirm_enqueues_only(self):
        calls = []
        response = route_callback({"from": {"id": 5}, "data": "ui:confirm:email:b1"},
                                  book_lookup=lambda _: BOOK,
                                  enqueue_request=lambda *args: calls.append(args) or "req-1",
                                  environ={"TELEGRAM_ALLOWED_USER_IDS": "5"})
        self.assertEqual(calls, [(5, "email", "b1")])
        self.assertIn("Not yet sent", response["text"])

    def test_choose_no_delivery(self):
        response = route_callback({"from": {"id": 5}, "data": "ui:choose:tg:b1"},
                                  book_lookup=lambda _: BOOK,
                                  enqueue_request=lambda *args: self.fail("Must not enqueue"), 
                                  environ={"TELEGRAM_ALLOWED_USER_IDS": "5"})
        self.assertIn("Confirm delivery", response["text"])


if __name__ == "__main__":
    unittest.main()
