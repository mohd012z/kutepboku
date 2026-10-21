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
        # Keep the built-in agent hermetic: don't touch the real state file.
        self.agent_mock = MagicMock()
        self.agent_mock.record_search.side_effect = lambda *a, **k: (10, 1)
        self.agent_mock.summary_text.side_effect = lambda: "agent test"
        self.agent_patch = patch("bot_router.agent_skills",
                                 return_value=self.agent_mock)
        self.agent_patch.start()

    async def asyncTearDown(self):
        self.agent_patch.stop()
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

    async def test_link_delivery_sends_url_and_nav(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {
            "book": dict(BOOK), "results": [dict(BOOK)],
            "search_token": "abcdef123456", "current_page": 0,
            "search_query": "machine learning"})
        update = self.callback("dl:l")
        await handle_update(update, MagicMock(), store=self.store)
        # results are kept so "back to results" works
        self.assertEqual(self.store.get_session(12345)[0], "CHOOSE_DELIVERY")
        sent = update.callback_query.message.reply_text.await_args
        self.assertIn("https://archive.org/download/x/book.pdf", sent.args[0])
        nav = [btn["callback_data"] for row in sent.kwargs["reply_markup"]
               ["inline_keyboard"] for btn in row]
        self.assertIn("dlb:back", nav)
        self.assertIn("dlb:more", nav)

    async def test_file_delivery_sends_document_and_nav(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {
            "book": dict(BOOK), "results": [dict(BOOK)],
            "search_token": "abcdef123456", "current_page": 0,
            "search_query": "machine learning"})
        update = self.callback("dl:f")
        with patch("bot_router.deliver_file", return_value=("pdf",
                    "https://archive.org/download/x/book.pdf")) as dl:
            await handle_update(update, MagicMock(), store=self.store)
        dl.assert_called_once()
        self.assertEqual(self.store.get_session(12345)[0], "CHOOSE_DELIVERY")
        replies = [c.args[0] for c in
                   update.callback_query.message.reply_text.await_args_list]
        self.assertTrue(any(r.startswith("✅ Sent (.pdf)") for r in replies))
        nav = [btn["callback_data"] for row in
               update.callback_query.message.reply_text.await_args_list[-1]
               .kwargs["reply_markup"]["inline_keyboard"] for btn in row]
        self.assertIn("dlb:back", nav)

    async def test_file_delivery_failure_falls_back_to_link(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {
            "book": dict(BOOK), "results": [dict(BOOK)],
            "search_token": "abcdef123456", "current_page": 0,
            "search_query": "machine learning"})
        update = self.callback("dl:f")
        with patch("bot_router.deliver_file", side_effect=ValueError("too big")):
            await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "CHOOSE_DELIVERY")
        replies = [c.args[0] for c in
                   update.callback_query.message.reply_text.await_args_list]
        self.assertTrue(any("delivery failed" in r for r in replies))

    async def test_dlb_back_returns_to_results(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {
            "book": dict(BOOK), "results": [dict(BOOK)],
            "search_token": "abcdef123456", "current_page": 0,
            "search_query": "machine learning"})
        update = self.callback("dlb:back")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "SELECTING_BOOK")
        data = [btn["callback_data"] for row in
                update.callback_query.edit_message_text.await_args.kwargs
                ["reply_markup"]["inline_keyboard"] for btn in row]
        self.assertIn("sr:b:abcdef123456:book_1", data)

    async def test_dlb_more_returns_home(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {
            "book": dict(BOOK), "results": [dict(BOOK)],
            "search_token": "abcdef123456"})
        update = self.callback("dlb:more")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "MENU")
        self.assertIn("msasoup",
                      update.callback_query.edit_message_text.await_args.args[0])

    async def test_dlb_back_without_results_alerts(self):
        self.store.set_session(12345, "CHOOSE_DELIVERY", {"book": dict(BOOK)})
        update = self.callback("dlb:back")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertIn("No results to go back to.",
                      update.callback_query.answer.await_args.args[0])

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
        self.assertEqual(seen, ["hacking penetration testing security"])

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

    async def test_command_termux_shows_menu(self):
        from ai_assistant import TERMUX_MENU_TEXT
        update = self.message("/termux")
        await handle_update(update, MagicMock(), store=self.store)
        text = update.message.reply_text.await_args.args[0]
        self.assertEqual(text, TERMUX_MENU_TEXT)
        kb = update.message.reply_text.await_args.kwargs["reply_markup"]
        data = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        self.assertEqual(len(kb["inline_keyboard"]), 15)
        self.assertIn("termux:pkg", data)
        self.assertIn("fa:run:termux", data)   # chat-automation tools
        self.assertIn("fa:run:termuxre", data)  # Termux RE (r2/jadx/apktool)
        self.assertIn("termux:ghidra", data)    # Termux + Ghidra
        self.assertIn("termux:radare2", data)   # Termux + radare2
        self.assertIn("termux:frida", data)     # Termux + Frida
        self.assertIn("termux:hbctool", data)   # Termux + hbctool
        self.assertIn("termux:flutter", data)   # Termux + Flutter (blutter)
        self.assertIn("termux:ytdlp", data)     # Termux + yt-dlp (media)
        self.assertIn("fa:run:reverse", data)   # related RE tools
        self.assertIn("fa:run:cloning", data)   # related cloning tools
        self.assertIn("termux:books", data)

    async def test_termux_re_howto_buttons(self):
        for action, marker in (("ghidra", "ghidraRun"),
                               ("radare2", "pkg install radare2"),
                               ("frida", "frida-server"),
                               ("hbctool", "hbctool disasm"),
                               ("flutter", "blutter"),
                               ("ytdlp", "pkg install python-yt-dlp ffmpeg")):
            with self.subTest(action=action):
                update = self.callback(f"termux:{action}")
                await handle_update(update, MagicMock(), store=self.store)
                up = update.callback_query.edit_message_text.await_args
                self.assertIn(marker, up.args[0])
                data = [b["callback_data"]
                        for row in up.kwargs["reply_markup"]["inline_keyboard"]
                        for b in row]
                self.assertIn("fa:run:termuxre", data)
                self.assertIn("termux:menu", data)

    async def test_termux_menu_callback_edits(self):
        from ai_assistant import termux_menu
        update = self.callback("termux:menu")
        await handle_update(update, MagicMock(), store=self.store)
        up = update.callback_query.edit_message_text.await_args
        menu = termux_menu()
        self.assertEqual(up.args[0], menu["text"])
        self.assertEqual(up.kwargs["reply_markup"], menu["reply_markup"])

    def test_find_menu_excludes_termux(self):
        from ai_assistant import find_menu
        data = [b["callback_data"] for row in find_menu()["reply_markup"]["inline_keyboard"]
                for b in row]
        self.assertIn("fa:run:hacking", data)
        self.assertNotIn("fa:run:termux", data)  # termux has its own menu now

    def test_home_and_auto_menu_link_termux_menu(self):
        from ai_assistant import home_menu, auto_menu
        for menu in (home_menu(), auto_menu()):
            data = [b["callback_data"]
                    for row in menu["reply_markup"]["inline_keyboard"] for b in row]
            self.assertIn("termux:menu", data)
            self.assertNotIn("fa:run:termux", data)

    async def test_fa_run_key_subtopic_resolves(self):
        # Regression: fa:run:cloning used to fall through (== "run" exact
        # match) so home sub-topic buttons did nothing.
        seen = []
        update = self.callback("fa:run:cloning")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider(seen=seen))
        self.assertIn("website cloning web scraping", seen)

    async def test_reply_long_splits_overlimit(self):
        from bot_router import _reply_long
        sent = []
        class M:
            async def reply_text(self, text, **kwargs):
                sent.append((text, kwargs))
        big = "\n".join("line %d %s" % (i, "x" * 60) for i in range(120))
        await _reply_long(M(), big, reply_markup={"k": 1})
        self.assertGreater(len(sent), 1)  # was split
        for text, kwargs in sent[:-1]:
            self.assertLessEqual(len(text), 4000)
            self.assertNotIn("reply_markup", kwargs)
        self.assertIn("reply_markup", sent[-1][1])
        self.assertEqual("\n".join(t for t, _ in sent), big)

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
        self.assertEqual(len(commands), 19)
        self.assertEqual(commands[0]["command"], "start")
        names = [c["command"] for c in commands]
        self.assertIn("find", names)
        self.assertIn("marketing", names)
        self.assertIn("agent", names)
        self.assertIn("prompt", names)
        self.assertIn("clone", names)
        self.assertIn("tginfo", names)
        self.assertIn("webscam", names)
        for entry in commands:
            self.assertTrue(entry["description"])
            self.assertLessEqual(len(entry["description"]), 256)

    # ---- built-in agent --------------------------------------------------
    async def test_search_records_agent_study(self):
        update = self.message("machine learning")
        await handle_update(update, MagicMock(), store=self.store,
                            search_provider=self.provider())
        self.agent_mock.record_search.assert_called_once_with(
            "machine learning", 1, source="ebook")
        reply = update.message.reply_text.await_args.args[0]
        self.assertIn("🧠 +10 XP → L1", reply)

    async def test_agent_command_shows_summary(self):
        update = self.message("/agent")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(
            update.message.reply_text.await_args.args[0], "agent test")

    async def test_marketing_command_runs_find_all_marketing(self):
        update = self.message("/marketing")
        with patch("bot_router.find_all", return_value={
                "topic": "ai marketing advertising", "ebooks": [],
                "apps": [{"id": "a/b", "title": "b",
                          "url": "https://github.com/a/b"}]}):
            await handle_update(update, MagicMock(), store=self.store,
                                search_provider=self.provider())
        self.assertEqual(self.store.get_session(12345)[0], "FIND_RESULT")

    async def test_agent_button_edits_to_summary(self):
        update = self.callback("ui:agent")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(
            update.callback_query.edit_message_text.await_args.args[0],
            "agent test")

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


class FindAllRouterTests(RouterTests):
    """Find ALL: ebooks + apps combined flow."""

    def _fa_result(self):
        return {
            "topic": "ai agent",
            "ebooks": [dict(BOOK)],
            "apps": [{"id": "owner/repo", "title": "repo — an agent",
                      "url": "https://github.com/owner/repo", "aid": "x"}],
        }

    async def test_find_command_opens_menu(self):
        update = self.message("/find")
        await handle_update(update, MagicMock(), store=self.store)
        markup = update.message.reply_text.await_args.kwargs["reply_markup"]
        data = [btn["callback_data"] for row in markup["inline_keyboard"]
                for btn in row]
        self.assertIn("fa:run", data)
        self.assertIn("fa:run:agents", data)
        self.assertIn("fa:run:webauto", data)

    async def test_find_run_button_prompts_for_topic(self):
        update = self.callback("fa:run")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "FIND_TOPIC")
        self.assertIn("What topic?",
                      update.callback_query.message.reply_text.await_args.args[0])

    async def test_find_home_button_opens_menu(self):
        update = self.callback("fa:menu")
        await handle_update(update, MagicMock(), store=self.store)
        data = [btn["callback_data"] for row in
                update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]["inline_keyboard"]
                for btn in row]
        self.assertIn("fa:run", data)
        self.assertIn("fa:run:agents", data)

    async def test_typed_topic_runs_find_all(self):
        self.store.set_session(12345, "FIND_TOPIC", {})
        update = self.message("ai agent")
        with patch("bot_router.find_all", return_value=self._fa_result()):
            await handle_update(update, MagicMock(), store=self.store,
                                search_provider=self.provider())
        self.assertEqual(self.store.get_session(12345)[0], "FIND_RESULT")
        markup = update.message.reply_text.await_args.kwargs["reply_markup"]
        data = [btn["callback_data"] for row in markup["inline_keyboard"]
                for btn in row]
        self.assertTrue(any(d.startswith("fae:") for d in data))
        self.assertTrue(any(d.startswith("fap:") for d in data))

    async def test_cancel_in_find_topic(self):
        self.store.set_session(12345, "FIND_TOPIC", {})
        update = self.message("cancel")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))

    async def test_fae_opens_standard_book_list(self):
        token = "abcdef123456"
        self.store.set_session(12345, "FIND_RESULT",
                               {"result": self._fa_result(), "fa_token": token})
        update = self.callback("fae:" + token)
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "SELECTING_BOOK")
        data = [btn["callback_data"] for row in
                update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]["inline_keyboard"]
                for btn in row]
        self.assertTrue(any(d.startswith("sr:b:") for d in data))

    async def test_fae_wrong_token_expires(self):
        self.store.set_session(12345, "FIND_RESULT",
                               {"result": self._fa_result(),
                                "fa_token": "abcdef123456"})
        update = self.callback("fae:" + "111111222222")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345)[0], "FIND_RESULT")
        self.assertIn("expired", update.callback_query.answer.await_args.args[0])

    async def test_fap_sends_repo_zip(self):
        token = "abcdef123456"
        self.store.set_session(12345, "FIND_RESULT",
                               {"result": self._fa_result(), "fa_token": token})
        update = self.callback("fap:" + token + ":0")
        with patch("bot_router._send_repo_zip", new=AsyncMock()) as send:
            await handle_update(update, MagicMock(), store=self.store)
        self.assertTrue(send.await_count >= 1)
        item = send.await_args.args[3]
        self.assertEqual(item["id"], "owner/repo")


class PromptForgeRouterTests(RouterTests):
    """Prompt Forge: /prompt -> pick capability -> type goal -> forged prompt."""

    async def test_prompt_command_opens_forge_menu(self):
        update = self.message("/prompt")
        await handle_update(update, MagicMock(), store=self.store)
        markup = update.message.reply_text.await_args.kwargs["reply_markup"]
        data = [btn["callback_data"] for row in markup["inline_keyboard"]
                for btn in row]
        self.assertIn("pf:cap:developer", data)
        self.assertIn("pf:cap:video", data)

    async def test_cap_callback_prompts_for_goal(self):
        update = self.callback("pf:cap:data")
        await handle_update(update, MagicMock(), store=self.store)
        state, sdata = self.store.get_session(12345)
        self.assertEqual(state, "FORGE_TOPIC")
        self.assertEqual(sdata["cap"], "data")
        self.assertIn("describe the task",
                      update.callback_query.edit_message_text.await_args.args[0])

    async def test_typed_goal_forges_prompt(self):
        self.store.set_session(12345, "FORGE_TOPIC", {"cap": "developer"})
        forged = {"capability": "developer", "label": "💻 Developer",
                  "prompt": "ROLE\nYou are...\nTASK\n..." * 6,
                  "mode": "template", "sections": 7}
        update = self.message("fix a race condition")
        with patch("bot_router.forge_prompt", return_value=forged) as forge:
            await handle_update(update, MagicMock(), store=self.store)
        forge.assert_called_once_with("developer", "fix a race condition", "")
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))
        # [0] is the "Forging…" progress message; [1] is the forged prompt
        self.assertIn("Forging",
                      update.message.reply_text.await_args_list[0].args[0])
        text = update.message.reply_text.await_args_list[1].args[0]
        self.assertIn("ROLE", text)
        self.assertIn("```", text)
        # agent studied it
        self.agent_mock.record_search.assert_called_once_with(
            "prompt:developer", 1, source="prompt")

    async def test_goal_with_context_passes_context(self):
        self.store.set_session(12345, "FORGE_TOPIC", {"cap": "analysis"})
        update = self.message("summarize the report\n\nIt's Q3, 40 pages.")
        with patch("bot_router.forge_prompt", return_value={
                "capability": "analysis", "label": "📊 Analysis",
                "prompt": "ROLE\nx" * 20, "mode": "template", "sections": 7}) as forge:
            await handle_update(update, MagicMock(), store=self.store)
        self.assertIsNotNone(forge.call_args)
        self.assertEqual(forge.call_args.args,
                         ("analysis", "summarize the report",
                          "It's Q3, 40 pages."))

    async def test_cancel_in_forge_topic(self):
        self.store.set_session(12345, "FORGE_TOPIC", {"cap": "general"})
        update = self.message("cancel")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(self.store.get_session(12345), ("IDLE", {}))


if __name__ == "__main__":
    unittest.main()
