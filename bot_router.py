"""Async Telegram update router with injected, verified search results."""
import asyncio
import logging
import os
import secrets

from session_manager import SessionManager
from search_pagination import build_search_keyboard, new_search_session, process_search_callback

log = logging.getLogger(__name__)
db = None


def session_store():
    global db
    if db is None:
        db = SessionManager(os.getenv("BOT_DB_PATH", "bot_sessions.db"))
    return db


async def handle_update(update, context, *, search_provider=None, store=None):
    store = store or session_store()
    user = getattr(update, "effective_user", None)
    if user is None:
        return
    user_id = user.id
    allowed = {int(value.strip()) for value in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
               if value.strip().isdigit()}
    if user_id not in allowed:
        callback = getattr(update, "callback_query", None)
        if callback is not None:
            await callback.answer("Not authorized", show_alert=True)
        return
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        result = process_search_callback(
            user_id, callback.data, load_session=store.get_session,
            save_session=store.set_session, clear_session=store.clear_session)
        await callback.answer("" if result["ok"] else result["error"],
                              show_alert=not result["ok"])
        if not result["ok"]:
            return
        if result["action"] == "page":
            await callback.edit_message_text(
                "Choose an eBook", reply_markup=result["keyboard"])
        elif result["action"] == "selected":
            await callback.edit_message_text(
                "Selected: " + str(result["book"]["title"]) + "\\nChoose delivery.")
        elif result["action"] == "cancel":
            await callback.edit_message_text("Search cancelled.")
        return
    message = getattr(update, "message", None)
    if message is None or not isinstance(getattr(message, "text", None), str):
        return
    text = message.text.strip()
    if text == "/cancel":
        store.clear_session(user_id)
        await message.reply_text("Cancelled.")
        return
    if text == "/start":
        store.set_session(user_id, "WAITING_FOR_QUERY", {})
        await message.reply_text("Welcome to kutepboku. Send an eBook search topic.")
        return
    state, _ = store.get_session(user_id)
    if state != "WAITING_FOR_QUERY" or not text:
        await message.reply_text("Send /start to begin a search.")
        return
    if search_provider is None:
        await message.reply_text("Search is not configured yet.")
        return
    try:
        results = await search_provider(text)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Verified search failed")
        await message.reply_text("Search is temporarily unavailable. Please try again later.")
        return
    if not isinstance(results, list) or not results:
        await message.reply_text("No verified books found.")
        return
    token = secrets.token_hex(6)
    data = new_search_session(text, results, token)
    store.set_session(user_id, "SELECTING_BOOK", data)
    await message.reply_text(
        "Choose an eBook", reply_markup=build_search_keyboard(results, 0, token))
