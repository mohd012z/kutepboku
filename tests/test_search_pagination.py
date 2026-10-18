import unittest
from search_pagination import build_search_keyboard, process_search_callback, new_search_session

TOKEN = "abcdef123456"
BOOKS = [{"id": "book_" + str(i), "title": "Book " + str(i)} for i in range(1, 6)]


class PaginationTests(unittest.TestCase):
    def test_first_page(self):
        rows = build_search_keyboard(BOOKS, 0, TOKEN)["inline_keyboard"]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[3][0]["text"], "Next ➡️")

    def test_last_page(self):
        rows = build_search_keyboard(BOOKS, 1, TOKEN)["inline_keyboard"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[2][0]["text"], "⬅️ Previous")

    def test_page_bounds(self):
        with self.assertRaises(ValueError):
            build_search_keyboard(BOOKS, 2, TOKEN)
        with self.assertRaises(ValueError):
            build_search_keyboard(BOOKS, -1, TOKEN)

    def test_empty_results(self):
        self.assertEqual(len(build_search_keyboard([], 0, TOKEN)["inline_keyboard"]), 1)

    def test_callback_stale_token(self):
        state, data = "SELECTING_BOOK", new_search_session("python", BOOKS, TOKEN)
        result = process_search_callback(7, "sr:p:000000000000:1",
            load_session=lambda _: (state, data), save_session=lambda *a: None,
            clear_session=lambda _: None)
        self.assertFalse(result["ok"])

    def test_page_update(self):
        state, data = "SELECTING_BOOK", new_search_session("python", BOOKS, TOKEN)
        saved = []
        result = process_search_callback(7, "sr:p:" + TOKEN + ":1",
            load_session=lambda _: (state, data),
            save_session=lambda *args: saved.append(args),
            clear_session=lambda _: None)
        self.assertTrue(result["ok"])
        self.assertEqual(saved[0][2]["current_page"], 1)

    def test_reject_hidden_book(self):
        state, data = "SELECTING_BOOK", new_search_session("python", BOOKS, TOKEN)
        result = process_search_callback(7, "sr:b:" + TOKEN + ":book_5",
            load_session=lambda _: (state, data), save_session=lambda *a: None,
            clear_session=lambda _: None)
        self.assertFalse(result["ok"])

    def test_select_visible_book(self):
        state, data = "SELECTING_BOOK", new_search_session("python", BOOKS, TOKEN)
        saved = []
        result = process_search_callback(7, "sr:b:" + TOKEN + ":book_1",
            load_session=lambda _: (state, data),
            save_session=lambda *args: saved.append(args),
            clear_session=lambda _: None)
        self.assertTrue(result["ok"])
        self.assertEqual(saved[0][1], "CHOOSE_DELIVERY")

    def test_invalid_callback(self):
        result = process_search_callback(7, "sr:p:" + TOKEN + ":-1",
            load_session=lambda _: ("SELECTING_BOOK", new_search_session("x", BOOKS, TOKEN)),
            save_session=lambda *a: None, clear_session=lambda _: None)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
