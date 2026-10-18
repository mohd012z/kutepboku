"""Live Telegram polling entry point. Does not auto-restore or auto-deliver."""
import asyncio
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters

from agent import BOT_NAME
from bot_router import handle_update
from restore_db import verify_database_integrity
from search_provider import verified_search

log = logging.getLogger(__name__)


def keyboard_adapter(payload):
    if not isinstance(payload, dict) or "inline_keyboard" not in payload:
        return payload
    return InlineKeyboardMarkup.de_json(payload, None)


async def telegram_handler(update, context):
    """Convert framework-neutral markup to PTB objects at the API boundary."""
    message = update.effective_message
    callback = update.callback_query
    original_reply = getattr(message, "reply_text", None) if message else None
    original_edit = getattr(callback, "edit_message_text", None) if callback else None
    # PTB's reply_text requires InlineKeyboardMarkup, not a raw Bot API dict.
    # Adapt at the application boundary rather than monkeypatching Telegram objects.
    class MessageProxy:
        def __init__(self, original):
            self.text = original.text

        async def reply_text(self, text, **kwargs):
            if "reply_markup" in kwargs:
                kwargs["reply_markup"] = keyboard_adapter(kwargs["reply_markup"])
            return await original_reply(text, **kwargs)

    class CallbackProxy:
        def __init__(self, original):
            self.data = original.data

        async def answer(self, *args, **kwargs):
            return await original.answer(*args, **kwargs)

        async def edit_message_text(self, text, **kwargs):
            if "reply_markup" in kwargs:
                kwargs["reply_markup"] = keyboard_adapter(kwargs["reply_markup"])
            return await original_edit(text, **kwargs)

    class UpdateProxy:
        effective_user = update.effective_user
        message = MessageProxy(message) if update.message else None
        callback_query = CallbackProxy(callback) if callback else None

    await handle_update(UpdateProxy(), context, search_provider=verified_search)


async def verify_identity(application):
    me = await application.bot.get_me()
    if not me.is_bot or (me.username or "").lower() != BOT_NAME:
        raise RuntimeError("Telegram bot identity mismatch")
    log.info("Verified bot @%s", me.username)


def main():
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    if not os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip():
        raise SystemExit("TELEGRAM_ALLOWED_USER_IDS is required (deny by default)")
    db = Path(os.getenv("BOT_DB_PATH", "bot_sessions.db"))
    if db.exists() and not verify_database_integrity(db):
        raise SystemExit("Existing session database failed integrity validation")
    application = ApplicationBuilder().token(token).post_init(verify_identity).build()
    application.add_handler(CallbackQueryHandler(telegram_handler, pattern=r"^sr:"))
    application.add_handler(MessageHandler(filters.TEXT, telegram_handler))
    log.info("Starting polling; startup recovery is deliberately disabled")
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
