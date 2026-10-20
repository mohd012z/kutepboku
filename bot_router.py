"""Async Telegram update router: msasoup conversational eBook assistant.

Flow:
  /start or Home button -> category menu (buttons)
  category / typed request -> search (Minda intent + IA discovery + CC gate
    + Minda relevance) -> paginated book list
  book tapped -> "Send file here" / "Link only"
  Send file -> download + sendDocument; Link -> archive.org URL
  LLM unavailable -> raw-topic search fallback (never blocks)
"""
import asyncio
import os
import secrets

import requests

from session_manager import SessionManager
from search_pagination import (build_search_keyboard, new_search_session,
                               process_search_callback)
from ai_assistant import (HELP_TEXT, _chat_reply, ask_intent, auto_menu,
                          category_topic, deliver_file, delivery_keyboard,
                          home_menu, mql5_menu)
from mql5_scout import (MQL5_LISTINGS, mql5_item_by_index, mql5_paged_message,
                        scrape_trending)
from mql5_scout import deliver_file as mql5_deliver_file
from auto_scout import (_TOOL_LOOKUP, _default_branch, deliver_zip,
                        trending_repos)

# callback key ("mt5:ea") -> (market, kind)
_MQL5_LOOKUP = {key: (market, kind) for key, _label, market, kind in MQL5_LISTINGS}

db = None

# Leading words users often prepend to a book topic; stripped before the
# search so "Search ebook bbma" is treated as the topic "bbma".
_QUERY_FILLER = (
    "search for", "search ebook", "search e-books", "search books", "search book",
    "search about", "search", "find for", "find me a", "find me", "find an",
    "find the", "find a", "find", "look for", "look up", "lookup", "look up",
    "ebooks about", "ebook about", "ebooks of", "ebook of", "books about",
    "book about", "books on", "book on", "about",
)


def _clean_query(text):
    """Strip leading filler words, keeping only the actual topic."""
    t = (text or "").strip()
    prev = None
    while prev != t and t:
        prev = t
        for filler in _QUERY_FILLER:
            if t.lower().startswith(filler):
                t = t[len(filler):].strip(" ,:;-")
                break
    return t or (text or "").strip()


def session_store():
    global db
    if db is None:
        db = SessionManager(os.getenv("BOT_DB_PATH", "bot_sessions.db"))
    return db


def _is_allowed(user_id):
    allowed = {int(value.strip()) for value in
               os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
               if value.strip().isdigit()}
    return user_id in allowed


async def _search_and_present(message, user_id, topic, store, search_provider):
    """Run the provider and show the paginated book list (or an explanation)."""
    if search_provider is None:
        await message.reply_text("Search is not configured yet.")
        return
    results = await search_provider(topic)
    if not isinstance(results, list) or not results:
        await message.reply_text(
            "No open-licensed books found for “" + topic[:60] + "”.\n"
            "Only explicitly CC-licensed (open) documents are offered, so "
            "results are sparse — try a broader topic (e.g. machine learning, "
            "chemistry, philosophy).")
        store.set_session(user_id, "MENU", {})
        return
    token = secrets.token_hex(6)
    data = new_search_session(topic, results, token)
    store.set_session(user_id, "SELECTING_BOOK", data)
    await message.reply_text(
        "📚 Found " + str(len(results)) + " open-licensed book(s) for “"
        + topic[:60] + "” — pick one:",
        reply_markup=build_search_keyboard(results, 0, token))


async def _deliver(callback, user_id, store, book, mode):
    """mode 'file' -> download + sendDocument; 'link' -> send the URL."""
    message = callback.message
    if mode == "link":
        url = str(book.get("source_url", ""))
        if not url:
            await message.reply_text("Link unavailable for this book.")
            return
        await message.reply_text("🔗 " + str(book.get("title", "Open eBook"))[:120]
                                 + "\n" + url)
        store.clear_session(user_id)
        return
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = str(os.getenv("TELEGRAM_DELIVERY_CHAT_ID") or user_id)
    await message.reply_text("⏳ Downloading — files up to 20 MB take a moment…")
    url = str(book.get("source_url", ""))
    try:
        ext, _ = await asyncio.to_thread(deliver_file, token, chat_id, book)
    except Exception:
        await message.reply_text("File delivery failed — direct link instead:\n" + url)
        store.clear_session(user_id)
        return
    await message.reply_text("✅ Sent (." + ext + "). Direct link:\n" + url)
    store.clear_session(user_id)


async def _run_action(action, user_id, store, message, intent_result, raw_text):
    """Dispatch a non-search intent. Returns True when handled."""
    if action == "home":
        store.set_session(user_id, "MENU", {})
        menu = home_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return True
    if action == "help":
        await message.reply_text(HELP_TEXT)
        return True
    if action == "cancel":
        store.clear_session(user_id)
        await message.reply_text("Cancelled.")
        return True
    if action == "chat":
        reply = _chat_reply(intent_result, raw_text)
        if reply:
            await message.reply_text(reply)
        return True
    return False


async def _send_repo_zip(update, user_id, store, item):
    """Resolve branch, download the repo zip, sendDocument; >20 MB or any
    failure falls back to the repo link. `item` needs id/title/url."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = str(os.getenv("TELEGRAM_DELIVERY_CHAT_ID") or user_id)
    message = update.callback_query.message
    await update.callback_query.answer("⏳ Resolving + downloading…")
    repo = {**item}
    try:
        repo["branch"] = await asyncio.to_thread(_default_branch, item["id"])
        size, _ = await asyncio.to_thread(
            deliver_zip, token, chat_id, repo, session=requests)
    except ValueError as err:
        if message is not None:
            await message.reply_text("🔗 " + item["id"] + " — " + str(err)
                                     + ":\n" + item["url"])
        return
    except Exception:
        if message is not None:
            await message.reply_text("⚠️ Download failed — repo link instead:\n"
                                     + item["url"])
        return
    if message is not None:
        await message.reply_text("✅ Sent " + item["id"] + " ("
                                 + str(round(size / 1024)) + " KB)\n" + item["url"])


async def handle_update(update, context, *, search_provider=None, store=None):
    store = store or session_store()
    user = getattr(update, "effective_user", None)
    if user is None:
        return
    user_id = user.id
    if not _is_allowed(user_id):
        callback = getattr(update, "callback_query", None)
        if callback is not None:
            await callback.answer("Not authorized", show_alert=True)
        return

    # ---- callbacks ------------------------------------------------------
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        data = callback.data or ""
        if data.startswith("sr:"):
            result = process_search_callback(
                user_id, data, load_session=store.get_session,
                save_session=store.set_session, clear_session=store.clear_session)
            await callback.answer("" if result["ok"] else result["error"],
                                   show_alert=not result["ok"])
            if not result["ok"]:
                return
            if result["action"] == "page":
                await callback.edit_message_text(
                    "Choose an eBook", reply_markup=result["keyboard"])
            elif result["action"] == "selected":
                store.set_session(user_id, "CHOOSE_DELIVERY", {"book": result["book"]})
                await callback.edit_message_text(
                    "📖 " + str(result["book"]["title"])[:120] + "\n\n"
                    "How should I deliver it?",
                    reply_markup=delivery_keyboard())
            elif result["action"] == "cancel":
                store.clear_session(user_id)
                await callback.edit_message_text("Search cancelled.")
            return
        if data.startswith("dl:"):
            mode = data[3:]
            state, sdata = store.get_session(user_id)
            book = sdata.get("book") if isinstance(sdata, dict) else None
            if state != "CHOOSE_DELIVERY" or not isinstance(book, dict) \
                    or not book.get("source_url"):
                await callback.answer("This selection has expired.", show_alert=True)
                await callback.edit_message_text(
                    "Expired — tap /start and pick again.")
                return
            await callback.answer("Sending link…" if mode == "l" else "Downloading…")
            await _deliver(callback, user_id, store, book, mode)
            return
        if data.startswith("mql5:"):
            # trending listing request: "mql5:mt5:ea" | "mql5:mt5:ind" | ...
            if data == "mql5:menu":
                menu = mql5_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            parts = data.split(":")
            key = ":".join(parts[1:])
            if key not in _MQL5_LOOKUP:
                await callback.answer("Unknown MQL5 listing.", show_alert=True)
                return
            market, kind = _MQL5_LOOKUP[key]
            await callback.answer("📡 Loading MQL5 trending…")
            try:
                items = await asyncio.to_thread(scrape_trending, market, kind)
            except Exception:
                await callback.edit_message_text(
                    "⚠️ Couldn't load the MQL5 Code Base right now "
                    "(site busy or layout changed). Try again in a minute.")
                return
            store.set_session(user_id, "MQL5_LISTING",
                              {"market": market, "kind": kind,
                               "items": items, "page": 0})
            page_msg = mql5_paged_message(items, 0)
            await callback.edit_message_text(page_msg["text"],
                                             reply_markup=page_msg["reply_markup"])
            return
        if data.startswith("mql5s:"):
            # page navigation within a stored MQL5 listing
            state, sdata = store.get_session(user_id)
            if state != "MQL5_LISTING" or not isinstance(sdata.get("items"), list):
                await callback.answer("This listing has expired.", show_alert=True)
                return
            try:
                page = int(data[6:])
                msg = mql5_paged_message(sdata["items"], page)
            except ValueError:
                await callback.answer("Bad page.", show_alert=True)
                return
            sdata["page"] = page
            store.set_session(user_id, state, sdata)
            await callback.answer("")
            await callback.edit_message_text(msg["text"], reply_markup=msg["reply_markup"])
            return
        if data.startswith("dlm:"):
            # send one item's file from the stored listing
            state, sdata = store.get_session(user_id)
            items = sdata.get("items") if isinstance(sdata, dict) else None
            if state != "MQL5_LISTING" or not isinstance(items, list):
                await callback.answer("This listing has expired.", show_alert=True)
                return
            try:
                item = mql5_item_by_index(items, data[4:])
            except ValueError as err:
                await callback.answer(str(err), show_alert=True)
                return
            message = callback.message
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = str(os.getenv("TELEGRAM_DELIVERY_CHAT_ID") or user_id)
            await callback.answer("⏳ Downloading…")
            try:
                kind, url, size = await asyncio.to_thread(
                    mql5_deliver_file, token, chat_id, item,
                    session=requests)
            except Exception:
                if message is not None:
                    await message.reply_text(
                        "⚠️ Download failed — item page link instead:\n" + item["url"])
                return
            if message is not None:
                await message.reply_text(
                    "✅ Sent " + item["title"][:80] + " (" + kind + ", "
                    + str(round(size / 1024)) + " KB)\n" + item["url"])
            return
        if data.startswith("auto:"):
            action = data[5:]
            if action == "menu":
                menu = auto_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            if action == "trend":
                await callback.answer("🔥 Loading GitHub trending…")
                try:
                    items = await asyncio.to_thread(trending_repos)
                except Exception:
                    await callback.edit_message_text(
                        "⚠️ Couldn't load GitHub trending right now "
                        "(site busy or layout changed). Try again in a minute.")
                    return
                store.set_session(user_id, "AUTO_LISTING", {"items": items})
                rows = [[{"text": it["title"][:60],
                          "callback_data": "autl:" + str(i)}]
                        for i, it in enumerate(items[:5])]
                rows.append([{"text": "🏠 Home", "callback_data": "ui:home"}])
                await callback.edit_message_text(
                    "🔥 Trending on GitHub right now — tap a repo to get "
                    "the source zip (link-only if >20 MB):",
                    reply_markup={"inline_keyboard": rows})
                return
            if action.startswith("tool:"):
                key = action[5:]
                label, full = _TOOL_LOOKUP.get(key, (None, None))
                if full is None:
                    await callback.answer("Unknown tool.", show_alert=True)
                    return
                await _send_repo_zip(update, user_id, store, {
                    "id": full, "title": label,
                    "url": "https://github.com/" + full})
                return
        if data.startswith("autl:"):
            state, sdata = store.get_session(user_id)
            items = sdata.get("items") if isinstance(sdata, dict) else None
            if state != "AUTO_LISTING" or not isinstance(items, list):
                await callback.answer("This listing has expired.", show_alert=True)
                return
            try:
                index = int(data[5:])
                if index < 0 or index >= len(items):
                    raise ValueError("bad index")
            except ValueError:
                await callback.answer("Bad item.", show_alert=True)
                return
            await _send_repo_zip(update, user_id, store, items[index])
            return
        if data.startswith("ui:"):
            action = data[3:]
            if action in ("home", "menu"):
                store.set_session(user_id, "MENU", {})
                menu = home_menu()
                await callback.edit_message_text(menu["text"],
                                                 reply_markup=menu["reply_markup"])
                return
            if action == "help":
                await callback.edit_message_text(HELP_TEXT)
                return
            if action == "cancel":
                store.clear_session(user_id)
                await callback.edit_message_text("Cancelled.")
                return
            if action.startswith("cat:"):
                topic = category_topic(action[4:])
                if topic is None:
                    await callback.answer("Unknown category.", show_alert=True)
                    return
                await callback.answer("🔎 Searching " + topic + "…")
                await _search_and_present(callback.message, user_id, topic,
                                          store, search_provider)
                return

    # ---- messages -------------------------------------------------------
    message = getattr(update, "message", None)
    if message is None or not isinstance(getattr(message, "text", None), str):
        return
    text = message.text.strip()
    if not text:
        return

    state, _sdata = store.get_session(user_id)

    if text in ("/start", "/menu", "/home"):
        store.set_session(user_id, "MENU", {})
        menu = home_menu()
        await message.reply_text(menu["text"], reply_markup=menu["reply_markup"])
        return
    if text == "/cancel":
        store.clear_session(user_id)
        await message.reply_text("Cancelled.")
        return
    if text == "/help":
        await message.reply_text(HELP_TEXT)
        return

    # mid-flow plain text starts a new action
    if state in ("SELECTING_BOOK", "CHOOSE_DELIVERY"):
        store.clear_session(user_id)

    # classify the message (LLM); fall back to raw-topic search
    intent_result = await asyncio.to_thread(ask_intent, text)
    if intent_result is None:
        intent_result = {"intent": "search", "topic": _clean_query(text)}
    action = intent_result["intent"]
    if action == "search":
        topic = (intent_result.get("topic") or _clean_query(text))
        if not topic:
            await message.reply_text("What topic should I search for? "
                                     "e.g. \"quantum computing\"")
            return
        await _search_and_present(message, user_id, topic, store, search_provider)
        return
    await _run_action(action, user_id, store, message, intent_result, text)
