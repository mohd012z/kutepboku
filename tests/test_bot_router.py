import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot_router import handle_update
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

    async def test_search_failure_reports_temporary_error(self):
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})
        async def provider(query):
            raise RuntimeError("simulated upstream failure")
        update = self.message("test query")
        await handle_update(update, MagicMock(), store=self.store, search_provider=provider)
        update.message.reply_text.assert_awaited_once_with(
            "Search is temporarily unavailable. Please try again later.")
        self.assertEqual(self.store.get_session(12345)[0], "WAITING_FOR_QUERY")

    async def test_search_cancellation_propagates(self):
        import asyncio
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})
        async def provider(query):
            raise asyncio.CancelledError()
        update = self.message("test query")
        with self.assertRaises(asyncio.CancelledError):
            await handle_update(update, MagicMock(), store=self.store, search_provider=provider)
        update.message.reply_text.assert_not_awaited()

    async def test_search_timeout_replies(self):
        import asyncio
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})
        async def provider(query):
            raise asyncio.TimeoutError()
        update = self.message("topic")
        await handle_update(update, MagicMock(), store=self.store, search_provider=provider)
        update.message.reply_text.assert_awaited_once_with(
            "Search timed out. Please try again later.")

    async def test_help_without_session(self):
        update = self.message("/help")
        await handle_update(update, MagicMock(), store=self.store)
        update.message.reply_text.assert_awaited_once_with("Commands: /start, /cancel, /help")

    async def test_long_query_not_sent_to_provider(self):
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})
        provider = AsyncMock()
        update = self.message("x" * 201)
        await handle_update(update, MagicMock(), store=self.store, search_provider=provider)
        provider.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with("Search query exceeds 200 characters.")

    async def test_unknown_command_not_searched(self):
        self.store.set_session(12345, "WAITING_FOR_QUERY", {})
        provider = AsyncMock()
        update = self.message("/unknown")
        await handle_update(update, MagicMock(), store=self.store, search_provider=provider)
        provider.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with("Unknown command. Send /help.")

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

    async def test_other_user_callback_cannot_use_owned_session(self):
        self.store.set_session(12345, "SELECTING_BOOK", {
            "results": [{"id": "book_1", "title": "Test"}],
            "search_token": "abcdef123456", "current_page": 0})
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USER_IDS": "12345,54321"}):
            update = self.callback("sr:b:abcdef123456:book_1", user_id=54321)
            await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "SELECTING_BOOK")
        self.assertEqual(self.store.get_session(54321)[0], "IDLE")
        update.callback_query.edit_message_text.assert_not_awaited()

    async def test_unauthorized_callback_denied(self):
        update = self.callback("sr:b:abcdef123456:book_1", user_id=999)
        await handle_update(update, MagicMock(), store=self.store)
        update.callback_query.answer.assert_awaited_once_with(
            "Not authorized", show_alert=True)
        update.callback_query.edit_message_text.assert_not_awaited()

    async def test_session_survives_manager_recreation(self):
        self.store.set_session(12345, "WAITING_FOR_QUERY", {"source": "test"})
        reopened = SessionManager(Path(self.temp.name) / "sessions.db")
        self.assertEqual(reopened.get_session(12345),
                         ("WAITING_FOR_QUERY", {"source": "test"}))

    async def test_compare_and_set_rejects_stale_snapshot(self):
        self.store.set_session(12345, "SELECTING_BOOK", {"page": 0})
        self.assertTrue(self.store.compare_and_set_session(
            12345, "SELECTING_BOOK", {"page": 0},
            "SELECTING_BOOK", {"page": 1}))
        self.assertFalse(self.store.compare_and_set_session(
            12345, "SELECTING_BOOK", {"page": 0},
            "CHOOSE_DELIVERY", {"book": "wrong"}))
        self.assertEqual(self.store.get_session(12345),
                         ("SELECTING_BOOK", {"page": 1}))

    async def test_compare_and_set_rejects_missing_session(self):
        self.assertFalse(self.store.compare_and_set_session(
            12345, "IDLE", {}, "SELECTING_BOOK", {"page": 0}))

    async def test_atomic_callback_rejects_stale_update(self):
        from search_pagination import process_search_callback
        self.store.set_session(12345, "SELECTING_BOOK", {
            "results": [{"id": "book_1", "title": "Test"}],
            "search_token": "abcdef123456", "current_page": 0})
        def stale_compare(*args):
            self.store.set_session(12345, "SELECTING_BOOK", {
                "results": [{"id": "book_1", "title": "Test"}],
                "search_token": "abcdef123456", "current_page": 1})
            return self.store.compare_and_set_session(*args)
        result = process_search_callback(
            12345, "sr:b:abcdef123456:book_1",
            load_session=self.store.get_session,
            save_session=self.store.set_session,
            clear_session=self.store.clear_session,
            compare_and_set=stale_compare)
        self.assertFalse(result["ok"])
        self.assertEqual(self.store.get_session(12345)[0], "SELECTING_BOOK")

    async def test_competing_atomic_writers_only_one_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        first = SessionManager(Path(self.temp.name) / "sessions.db")
        second = SessionManager(Path(self.temp.name) / "sessions.db")
        first.set_session(12345, "SELECTING_BOOK", {"page": 0})
        gate = Barrier(2)
        def attempt(manager, page):
            gate.wait(timeout=5)
            return manager.compare_and_set_session(
                12345, "SELECTING_BOOK", {"page": 0},
                "SELECTING_BOOK", {"page": page})
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(attempt, first, 1)
            two = pool.submit(attempt, second, 2)
            outcomes = [one.result(timeout=10), two.result(timeout=10)]
        self.assertEqual(sorted(outcomes), [False, True])
        state, data = self.store.get_session(12345)
        self.assertEqual(state, "SELECTING_BOOK")
        self.assertIn(data["page"], (1, 2))

    async def test_cancel_clears_session(self):
        self.store.set_session(12345, "SELECTING_BOOK", {"results": []})
        await handle_update(self.message("/cancel"), MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))


if __name__ == "__main__":
    unittest.main()
