import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot_router import handle_update, _clean_query
from session_manager import SessionManager


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionManager(Path(self.temp.name) / "sessions.db")
        self.auth = patch.dict(os.environ, {"TELEGRAM_ALLOWED_USER_IDS": "12345"})
        self.auth.start()

    async def asyncTearDown(self):
        self.auth.stop()
        self.temp.cleanup()

    def message(self, text, user_id=12345):
        update = MagicMock()
        update.effective_user.id = user_id
        update.callback_query = None
        update.message.text = text
        update.message.reply_text = AsyncMock()
        return update

    def callback(self, data, user_id=12345):
        update = MagicMock()
        update.effective_user.id = user_id
        update.message = None
        update.callback_query.data = data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        return update

    async def test_start_persists(self):
        update = self.message("/start")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "WAITING_FOR_QUERY")
        update.message.reply_text.assert_awaited_once()

    async def test_query_to_selection(self):
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})
        async def provider(query):
            return [{"id": "book_1", "title": "Verified test fixture"}]
        update = self.message("Python Architecture")
        await handle_update(update, MagicMock(), store=self.store, search_provider=provider)
        state, data = self.store.get_session(12345)
        self.assertEqual(state, "SELECTING_BOOK")
        self.assertEqual(data["search_query"], "Python Architecture")
        self.assertEqual(len(data["results"]), 1)
        update.message.reply_text.assert_awaited_once()

    async def test_selection_callback(self):
        self.store.set_session(12345, "SELECTING_BOOK", {
            "results": [{"id": "book_1", "title": "Test book"}],
            "search_token": "abcdef123456", "current_page": 0})
        update = self.callback("sr:b:abcdef123456:book_1")
        await handle_update(update, MagicMock(), store=self.store)
        state, data = self.store.get_session(12345)
        self.assertEqual(state, "CHOOSE_DELIVERY")
        self.assertEqual(data["selected_book"]["id"], "book_1")
        update.callback_query.edit_message_text.assert_awaited_once()

    async def test_stale_callback_rejected(self):
        self.store.set_session(12345, "SELECTING_BOOK", {
            "results": [{"id": "book_1", "title": "Test"}],
            "search_token": "abcdef123456", "current_page": 0})
        update = self.callback("sr:b:000000000000:book_1")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "SELECTING_BOOK")
        update.callback_query.edit_message_text.assert_not_awaited()

    async def test_unauthorized_user_denied(self):
        update = self.message("/start", user_id=999)
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(999)[0], "IDLE")
        update.message.reply_text.assert_not_awaited()

    async def test_cancel_clears_session(self):
        self.store.set_session(12345, "SELECTING_BOOK", {"results": []})
        await handle_update(self.message("/cancel"), MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))

    def test_clean_query_strips_filler(self):
        self.assertEqual(_clean_query("Search ebook bbma"), "bbma")
        self.assertEqual(_clean_query("search for python"), "python")
        self.assertEqual(_clean_query("Find a book about chemistry"), "chemistry")
        self.assertEqual(_clean_query("look up machine learning"), "machine learning")
        self.assertEqual(_clean_query("Search ebook"), "Search ebook")  # filler only -> unchanged

    def test_clean_query_keeps_real_topics(self):
        self.assertEqual(_clean_query("bbma"), "bbma")
        self.assertEqual(_clean_query("machine learning"), "machine learning")
        self.assertEqual(_clean_query(""), "")

    async def test_query_stripped_before_search(self):
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})
        seen = []

        async def provider(query):
            seen.append(query)
            return [{"id": "book_1", "title": "X"}]

        await handle_update(self.message("Search ebook bbma"), MagicMock(),
                            store=self.store, search_provider=provider)
        self.assertEqual(seen, ["bbma"])

    async def test_no_results_shows_guidance(self):
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})

        async def provider(query):
            return []

        update = self.message("bbma")
        await handle_update(update, MagicMock(), store=self.store, search_provider=provider)
        # stayed in WAITING_FOR_QUERY (not advanced to selection)
        self.assertEqual(self.store.get_session(12345)[0], "WAITING_FOR_QUERY")
        reply = update.message.reply_text.await_args.args[0]
        self.assertIn("No open-licensed books found for bbma", reply)
        self.assertIn("https://mohd012z.github.io/kutepboku/", reply)


if __name__ == "__main__":
    unittest.main()
