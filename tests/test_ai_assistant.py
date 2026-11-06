import unittest
from unittest import mock
from unittest.mock import MagicMock

import ai_assistant
from ai_assistant import (CATEGORIES, _parse_intent, ask_intent, category_topic,
                          deliver_file, delivery_keyboard, home_menu)


class IntentParserTests(unittest.TestCase):
    def test_parse_valid(self):
        out = _parse_intent({"intent": "search", "topic": "python"})
        if out is None:
            self.fail("expected a parsed intent")
        self.assertEqual(out["intent"], "search")
        self.assertEqual(out["topic"], "python")

    def test_parse_chat_topic_null(self):
        out = _parse_intent({"intent": "chat", "topic": None})
        self.assertIsNotNone(out)
        self.assertEqual(out, {"intent": "chat", "topic": None})

    def test_parse_rejects_unknown_intent(self):
        self.assertIsNone(_parse_intent({"intent": "dance", "topic": None}))

    def test_parse_rejects_non_dict(self):
        self.assertIsNone(_parse_intent("nope"))
        self.assertIsNone(_parse_intent(None))

    def test_parse_truncates_long_topic(self):
        out = _parse_intent({"intent": "search", "topic": "x" * 500})
        self.assertIsNotNone(out)
        self.assertEqual(len(out["topic"]), 200)

    def test_parse_requires_string_topic(self):
        self.assertIsNone(_parse_intent({"intent": "search"}))
        self.assertIsNone(_parse_intent({"intent": "search", "topic": 42}))


class AskIntentTests(unittest.TestCase):
    def _client(self, content):
        client = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={
            "choices": [{"message": {"content": content}}]})
        client.post = MagicMock(return_value=response)
        return client

    def test_returns_parsed_intent(self):
        client = self._client('{"intent": "search", "topic": "physics"}')
        out = ask_intent("find physics book", client=client,
                         base_url="http://x", api_key="k")
        if out is None:
            self.fail("expected a parsed intent")
        self.assertEqual(out["intent"], "search")
        self.assertEqual(out["topic"], "physics")

    def test_strips_json_fence(self):
        client = self._client('```json\n{"intent": "help", "topic": null}\n```')
        out = ask_intent("help", client=client, base_url="http://x", api_key="k")
        if out is None:
            self.fail("expected a parsed intent")
        self.assertEqual(out["intent"], "help")

    def test_malformed_json_returns_none(self):
        client = self._client("not json at all")
        self.assertIsNone(ask_intent("hi", client=client,
                                     base_url="http://x", api_key="k"))

    def test_missing_key_returns_none(self):
        self.assertIsNone(ask_intent("hi", client=self._client("{}"),
                                     base_url="http://x", api_key=""))

    def test_http_error_returns_none(self):
        client = MagicMock()
        client.post = MagicMock(side_effect=Exception("boom"))
        self.assertIsNone(ask_intent("hi", client=client,
                                     base_url="http://x", api_key="k"))


class MenuTests(unittest.TestCase):
    def test_home_menu_lists_all_categories(self):
        menu = home_menu()
        data = [btn["callback_data"] for row in menu["reply_markup"]["inline_keyboard"]
                for btn in row]
        for key, _label, _topic in CATEGORIES:
            self.assertIn("ui:cat:" + key, data)
        self.assertIn("ui:help", data)
        # every row must be two or fewer buttons (Telegram mobile)
        for row in menu["reply_markup"]["inline_keyboard"]:
            self.assertLessEqual(len(row), 2)

    def test_category_topic_lookup(self):
        self.assertEqual(category_topic("ml"), "machine learning")
        self.assertIsNone(category_topic("nope"))

    def test_delivery_keyboard_buttons(self):
        kb = delivery_keyboard()
        data = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
        self.assertEqual(data, ["dl:f", "dl:l", "ui:home"])


class DeliverFileTests(unittest.TestCase):
    def test_deliver_sends_document(self):
        book = {"title": "Great Book", "source_url": "https://archive.org/download/x/book.pdf"}
        session = MagicMock()
        with mock.patch.object(ai_assistant, "download",
                               return_value=("pdf", b"%PDF-1.4 " + b"x" * 2048)) as dl, \
                mock.patch.object(ai_assistant, "send") as snd:
            ext, url = deliver_file("123:T", "456", book, session=session)
        self.assertEqual(ext, "pdf")
        self.assertEqual(url, book["source_url"])
        dl.assert_called_once_with(session, book["source_url"])
        snd.assert_called_once()
        args = snd.call_args.args
        # send(session, token, chat, name, data, caption)
        self.assertEqual(args[0], session)
        self.assertEqual(args[1], "123:T")
        self.assertEqual(args[2], "456")
        self.assertEqual(args[3], "book.pdf")
        self.assertIn("https://archive.org/download/x/book.pdf", args[5])

    def test_deliver_propagates_download_failure(self):
        book = {"title": "Big", "source_url": "https://archive.org/download/x/book.pdf"}
        with mock.patch.object(ai_assistant, "download",
                               side_effect=ValueError("too big")):
            with self.assertRaises(ValueError):
                deliver_file("123:T", "456", book, session=MagicMock())


if __name__ == "__main__":
    unittest.main()
