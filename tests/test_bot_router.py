import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot_router import handle_update, _clean_query
from session_manager import SessionManager

BOOK = {"id": "book_1", "title": "Test book",
        "source_url": "https://archive.org/download/x/book.pdf"}


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionManager(Path(self.temp.name) / "sessions.db")
        self.env = patch.dict(os.environ, {
            "TELEGRAM_ALLOWED_USER_IDS": "12345",
            "TELEGRAM_BOT_TOKEN": "123:TEST",
            "MINDA_API_KEY": "",          # intent LLM off -> raw-topic fallback
            "MINDA_BASE_URL": "",
        })
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
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
        cb = MagicMock()
        cb.data = data
        cb.answer = AsyncMock()
        cb.edit_message_text = AsyncMock()
        cb.message.reply_text = AsyncMock()
        update.callback_query = cb
        return update

    def provider(self, results=None, seen=None):
        async def _provider(query):
            if seen is not None:
                seen.append(query)
            return results if results is not None else [dict(BOOK)]
        return _provider

    # ---- menu / commands ------------------------------------------------
    async def test_start_shows_home_menu(self):
        update = self.message("/start")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "MENU")
        call = update.message.reply_text.await_args
        self.assertIn("msasoup", call.args[0])
        markup = call.kwargs["reply_markup"]
        data = [btn["callback_data"] for row in markup["inline_keyboard"]
                for btn in row]
        self.assertIn("ui:cat:ml", data)
        self.assertIn("ui:cat:phys", data)

    async def test_slash_cancel_clears_session(self):
        self.store.set_session(12345, "SELECTING_BOOK", {"results": []})
        await handle_update(self.message("/cancel"), MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))

    # ---- text search (LLM off -> raw topic fallback) ---------------------
    async def test_plain_text_searches_cleaned_topic(self):
        seen = []
        update = self.message("Find me a book about chemistry")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["chemistry"])
        state, data = self.store.get_session(12345)
        self.assertEqual(state, "SELECTING_BOOK")
        self.assertEqual(data["search_query"], "chemistry")

    async def test_search_with_results_shows_keyboard(self):
        update = self.message("machine learning")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider())
        call = update.message.reply_text.await_args
        self.assertIn("open-licensed book(s)", call.args[0])
        self.assertIn("inline_keyboard", call.kwargs["reply_markup"])

    async def test_search_empty_shows_sparse_note(self):
        update = self.message("bbma")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(results=[]))
        self.assertEqual(self.store.get_session(12345)[0], "MENU")
        reply = update.message.reply_text.await_args.args[0]
        self.assertIn("No open-licensed books found for “bbma”", reply)

    async def test_search_without_provider(self):
        update = self.message("physics")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertIn("not configured", update.message.reply_text.await_args.args[0])

    # ---- callbacks --------------------------------------------------------
    async def test_book_select_shows_delivery_options(self):
        self.store.set_session(12345, "SELECTING_BOOK", {
            "results": [dict(BOOK)], "search_token": "abcdef123456",
            "current_page": 0})
        update = self.callback("sr:b:abcdef123456:book_1")
        await handle_update(update, MagicMock(), store=self.store)
        state, data = self.store.get_session(12345)
        self.assertEqual(state, "CHOOSE_DELIVERY")
        self.assertEqual(data["book"]["id"], "book_1")
        markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        data_list = [btn["callback_data"] for row in markup["inline_keyboard"]
                     for btn in row]
        self.assertIn("dl:f", data_list)
        self.assertIn("dl:l", data_list)

    async def test_stale_callback_rejected(self):
        self.store.set_session(12345, "SELECTING_BOOK", {
            "results": [dict(BOOK)], "search_token": "abcdef123456",
            "current_page": 0})
        update = self.callback("sr:b:000000000000:book_1")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "SELECTING_BOOK")
        update.callback_query.edit_message_text.assert_not_awaited()

    async def test_category_callback_searches_topic(self):
        seen = []
        update = self.callback("ui:cat:chem")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["chemistry"])
        self.assertEqual(self.store.get_session(12345)[0], "SELECTING_BOOK")

    async def test_home_callback_renders_menu(self):
        update = self.callback("ui:home")
        await handle_update(update, MagicMock(), store=self.store)
        text = update.callback_query.edit_message_text.await_args.args[0]
        self.assertIn("msasoup", text)

    async def test_link_delivery_sends_url(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {"book": dict(BOOK)})
        update = self.callback("dl:l")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))
        sent = update.callback_query.message.reply_text.await_args.args[0]
        self.assertIn("https://archive.org/download/x/book.pdf", sent)

    async def test_file_delivery_sends_document(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {"book": dict(BOOK)})
        update = self.callback("dl:f")
        with patch("bot_router.deliver_file", return_value=("pdf",
                    "https://archive.org/download/x/book.pdf")) as dl:
            await handle_update(update, MagicMock(), store=self.store)
        dl.assert_called_once()
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))
        replies = [c.args[0] for c in
                   update.callback_query.message.reply_text.await_args_list]
        self.assertTrue(any(r.startswith("✅ Sent (.pdf)") for r in replies))

    async def test_file_delivery_failure_falls_back_to_link(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {"book": dict(BOOK)})
        update = self.callback("dl:f")
        with patch("bot_router.deliver_file", side_effect=ValueError("too big")):
            await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))
        replies = [c.args[0] for c in
                   update.callback_query.message.reply_text.await_args_list]
        self.assertTrue(any("delivery failed" in r for r in replies))

    async def test_expired_delivery_rejected(self):
        self.store.set_session(12345, "MENU", {})
        update = self.callback("dl:l")
        await handle_update(update, MagicMock(), store=self.store)
        update.callback_query.message.reply_text.assert_not_awaited()

    async def test_unauthorized_user_denied(self):
        update = self.message("/start", user_id=999)
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(999)[0], "IDLE")
        update.message.reply_text.assert_not_awaited()

    # ---- LLM intent routing ----------------------------------------------
    async def test_llm_intent_home(self):
        with patch("bot_router.ask_intent",
                   return_value={"intent": "home", "topic": None}):
            update = self.message("take me home")
            await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "MENU")

    async def test_llm_intent_help(self):
        with patch("bot_router.ask_intent",
                   return_value={"intent": "help", "topic": None}):
            update = self.message("how do you work?")
            await handle_update(update, MagicMock(), store=self.store)
        self.assertIn("How I work", update.message.reply_text.await_args.args[0])

    async def test_llm_intent_chat_gives_book_guidance(self):
        with patch("bot_router.ask_intent",
                   return_value={"intent": "chat", "topic": None}):
            update = self.message("hello there")
            await handle_update(update, MagicMock(), store=self.store)
        self.assertIn("eBooks", update.message.reply_text.await_args.args[0])

    async def test_llm_search_uses_extracted_topic(self):
        seen = []
        with patch("bot_router.ask_intent",
                   return_value={"intent": "search",
                                 "topic": "quantum computing"}):
            update = self.message("find me a quantum computing book please")
            await handle_update(update, MagicMock(), store=self.store,
                                search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["quantum computing"])

    async def test_llm_unavailable_falls_back_to_raw_topic(self):
        seen = []
        with patch("bot_router.ask_intent", return_value=None):
            update = self.message("quantum computing")
            await handle_update(update, MagicMock(), store=self.store,
                                search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["quantum computing"])

    # ---- MQL5 trending callbacks -----------------------------------------
    async def test_mql5_menu_shows_listings(self):
        update = self.callback("mql5:menu")
        await handle_update(update, MagicMock(), store=self.store)
        text = update.callback_query.edit_message_text.await_args.args[0]
        self.assertIn("MQL5 Code Base", text)

    async def test_mql5_listing_scrapes_and_pages(self):
        items = [{"id": "78579", "title": "Prop Firm Guard",
                  "url": "https://www.mql5.com/en/code/78579"}]
        with patch("bot_router.scrape_trending", return_value=items) as st:
            update = self.callback("mql5:mt5:ea")
            await handle_update(update, MagicMock(), store=self.store)
        st.assert_called_once_with("mt5", "experts")
        state, data = self.store.get_session(12345)
        self.assertEqual(state, "MQL5_LISTING")
        self.assertEqual(data["items"], items)
        text = update.callback_query.edit_message_text.await_args.args[0]
        self.assertIn("Prop Firm Guard", text)

    async def test_mql5_listing_failure_shows_warning(self):
        with patch("bot_router.scrape_trending", side_effect=ValueError("boom")):
            update = self.callback("mql5:mt5:ea")
            await handle_update(update, MagicMock(), store=self.store)
        call = update.callback_query.edit_message_text.await_args
        self.assertIn("Couldn't load", call.args[0])

    async def test_mql5_page_navigation(self):
        items = [{"id": str(1000 + i), "title": "EA " + str(i),
                  "url": "https://x"} for i in range(10)]
        self.store.set_session(12345, "MQL5_LISTING",
                               {"market": "mt5", "kind": "experts",
                                "items": items, "page": 0})
        update = self.callback("mql5s:1")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[1]["page"], 1)
        update.callback_query.edit_message_text.assert_awaited()

    async def test_mql5_item_delivery(self):
        items = [{"id": "78579", "title": "Prop Firm Guard",
                  "url": "https://www.mql5.com/en/code/78579"}]
        self.store.set_session(12345, "MQL5_LISTING",
                               {"market": "mt5", "kind": "experts",
                                "items": items, "page": 0})
        update = self.callback("dlm:0")
        with patch("bot_router.mql5_deliver_file",
                   return_value=("source", "https://x/A.mq5", 2000)):
            await handle_update(update, MagicMock(), store=self.store)
        sent = update.callback_query.message.reply_text.await_args.args[0]
        self.assertIn("✅ Sent", sent)
        self.assertIn("Prop Firm Guard", sent)

    async def test_mql5_item_delivery_failure_link_fallback(self):
        items = [{"id": "78579", "title": "Prop Firm Guard",
                  "url": "https://www.mql5.com/en/code/78579"}]
        self.store.set_session(12345, "MQL5_LISTING",
                               {"market": "mt5", "kind": "experts",
                                "items": items, "page": 0})
        update = self.callback("dlm:0")
        with patch("bot_router.mql5_deliver_file", side_effect=ValueError("big")):
            await handle_update(update, MagicMock(), store=self.store)
        sent = update.callback_query.message.reply_text.await_args.args[0]
        self.assertIn("https://www.mql5.com/en/code/78579", sent)

    async def test_mql5_expired_listing_rejected(self):
        self.store.set_session(12345, "MENU", {})
        update = self.callback("dlm:0")
        await handle_update(update, MagicMock(), store=self.store)
        update.callback_query.message.reply_text.assert_not_awaited()

    # ---- automation tools callbacks --------------------------------------
    async def test_auto_menu_shows_tools(self):
        update = self.callback("auto:menu")
        await handle_update(update, MagicMock(), store=self.store)
        text = update.callback_query.edit_message_text.await_args.args[0]
        self.assertIn("Automation tools", text)
        markup = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        data = [btn["callback_data"] for row in markup["inline_keyboard"] for btn in row]
        self.assertIn("auto:trend", data)
        self.assertIn("auto:tool:nuclei", data)
        self.assertIn("auto:tool:uia2", data)

    async def test_auto_trending_lists_repos(self):
        items = [{"id": "owner/repo", "title": "owner/repo",
                  "url": "https://github.com/owner/repo"}]
        with patch("bot_router.trending_repos", return_value=items):
            update = self.callback("auto:trend")
            await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "AUTO_LISTING")
        call = update.callback_query.edit_message_text.await_args
        markup = call.kwargs["reply_markup"]
        data = [btn["callback_data"] for row in markup["inline_keyboard"]
                for btn in row]
        self.assertIn("autl:0", data)
        # repo name shown in a button
        self.assertTrue(any("owner/repo" in btn["text"]
                            for row in markup["inline_keyboard"] for btn in row))

    async def test_auto_trending_failure_warns(self):
        with patch("bot_router.trending_repos", side_effect=ValueError("x")):
            update = self.callback("auto:trend")
            await handle_update(update, MagicMock(), store=self.store)
        text = update.callback_query.edit_message_text.await_args.args[0]
        self.assertIn("Couldn't load GitHub trending", text)

    async def test_auto_tool_delivers_zip(self):
        update = self.callback("auto:tool:katana")
        with patch("bot_router._default_branch", return_value="dev"), \
             patch("bot_router.deliver_zip", return_value=(4000, "https://x")):
            await handle_update(update, MagicMock(), store=self.store)
        sent = update.callback_query.message.reply_text.await_args.args[0]
        self.assertIn("✅ Sent projectdiscovery/katana", sent)

    async def test_auto_tool_too_large_gives_link(self):
        update = self.callback("auto:tool:metasploit")
        with patch("bot_router._default_branch", return_value="master"), \
             patch("bot_router.deliver_zip",
                   side_effect=ValueError("Repo exceeds the 20 MB bot-file limit — link only")):
            await handle_update(update, MagicMock(), store=self.store)
        sent = update.callback_query.message.reply_text.await_args.args[0]
        self.assertIn("https://github.com/rapid7/metasploit-framework", sent)
        self.assertIn("🔗", sent)

    async def test_auto_trending_item_delivers(self):
        items = [{"id": "owner/repo", "title": "owner/repo",
                  "url": "https://github.com/owner/repo"}]
        self.store.set_session(12345, "AUTO_LISTING", {"items": items})
        update = self.callback("autl:0")
        with patch("bot_router._default_branch", return_value="main"), \
             patch("bot_router.deliver_zip", return_value=(2000, "https://x")):
            await handle_update(update, MagicMock(), store=self.store)
        sent = update.callback_query.message.reply_text.await_args.args[0]
        self.assertIn("✅ Sent owner/repo", sent)

    async def test_auto_trending_item_expired(self):
        self.store.set_session(12345, "MENU", {})
        update = self.callback("autl:0")
        await handle_update(update, MagicMock(), store=self.store)
        update.callback_query.message.reply_text.assert_not_awaited()

    # ---- bot commands (bottom-left ⋮ menu) --------------------------------
    async def test_command_forex_searches(self):
        seen = []
        update = self.message("/forex")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["forex trading"])

    async def test_command_hacking_searches(self):
        seen = []
        update = self.message("/hacking")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["hacking penetration testing automation"])

    async def test_command_android_searches(self):
        seen = []
        update = self.message("/android")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["android automation"])

    async def test_command_mql5_shows_menu(self):
        update = self.message("/mql5")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertIn("MQL5 Code Base", update.message.reply_text.await_args.args[0])

    async def test_command_tools_shows_menu(self):
        update = self.message("/tools")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertIn("Automation tools", update.message.reply_text.await_args.args[0])

    async def test_command_with_bot_suffix(self):
        seen = []
        update = self.message("/forex@mysoupsearchbot")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["forex trading"])

    async def test_unlisted_slash_goes_to_search(self):
        # "/foo" is not a bot command -> treated as a topic search
        seen = []
        update = self.message("/foo")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertEqual(seen, ["/foo"])

    def test_bot_command_markup_shape(self):
        from ai_assistant import bot_command_markup
        commands = bot_command_markup()
        self.assertEqual(len(commands), 9)
        self.assertEqual(commands[0]["command"], "start")
        for entry in commands:
            self.assertTrue(entry["description"])
            self.assertLessEqual(len(entry["description"]), 256)

    # ---- filler helpers (from PR #11) -------------------------------------
    def test_clean_query_strips_filler(self):
        self.assertEqual(_clean_query("Search ebook bbma"), "bbma")
        self.assertEqual(_clean_query("search for python"), "python")
        self.assertEqual(_clean_query("Find a book about chemistry"), "chemistry")
        self.assertEqual(_clean_query("look up machine learning"), "machine learning")
        self.assertEqual(_clean_query("Search ebook"), "Search ebook")

    def test_clean_query_keeps_real_topics(self):
        self.assertEqual(_clean_query("bbma"), "bbma")
        self.assertEqual(_clean_query("machine learning"), "machine learning")
        self.assertEqual(_clean_query(""), "")


if __name__ == "__main__":
    unittest.main()
