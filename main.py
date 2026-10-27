"""Live Telegram polling entry point. Does not auto-restore or auto-deliver."""
import asyncio
import logging
import os
import time
import sys
from pathlib import Path

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from telegram.error import Conflict, Forbidden, InvalidToken

from agent import BOT_NAME
from cloud_backup import backup_database_snapshot
from bot_router import handle_update
from restore_db import verify_database_integrity
from search_provider import verified_search
from status_metrics import format_status, status_snapshot
from runtime_guard import polling_lock

STARTED_AT = time.monotonic()

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
        # `message = ...` makes `message` a class-local in this body; the RHS
        # must read the non-shadowed source (identical to the local `message`
        # set above from update.effective_message).
        message = MessageProxy(update.effective_message) if update.message else None
        callback_query = CallbackProxy(callback) if callback else None

    await handle_update(UpdateProxy(), context, search_provider=verified_search)


async def verify_identity(application):
    me = await application.bot.get_me()
    if not me.is_bot or (me.username or "").lower() != BOT_NAME:
        raise RuntimeError("Telegram bot identity mismatch")
    webhook = await application.bot.get_webhook_info()
    if webhook.url:
        raise RuntimeError("Active Telegram webhook: refusing to replace another consumer")
    log.info("Verified bot @%s", me.username)


async def manual_backup_command(update, context):
    """Only the configured admin may upload an encrypted snapshot."""
    admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    user = update.effective_user
    message = update.message
    if not admin_id or not admin_id.isdecimal() or user is None or str(user.id) != admin_id:
        if message:
            await message.reply_text("Not authorized.")
        return
    if message is None or update.effective_chat is None or update.effective_chat.type != "private":
        return
    await message.reply_text("Creating encrypted database backup...")
    try:
        message_id = await asyncio.to_thread(backup_database_snapshot)
    except Exception:
        log.exception("Manual backup failed")
        await message.reply_text("Backup failed. Check secure server logs.")
        return
    await message.reply_text("Encrypted backup uploaded and pinned (message %d)." % message_id)


async def status_command(update, context):
    """Admin-only diagnostics; never reveal session contents or identifiers."""
    admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    user = update.effective_user
    message = update.message
    if not admin_id or not admin_id.isdecimal() or user is None or str(user.id) != admin_id:
        if message:
            await message.reply_text("Not authorized.")
        return
    if message is None or update.effective_chat is None or update.effective_chat.type != "private":
        return
    try:
        info = await asyncio.to_thread(status_snapshot, started_at=STARTED_AT)
        await message.reply_text(format_status(info))
    except Exception:
        log.exception("Status diagnostic failed")
        await message.reply_text("Diagnostics unavailable. Check secure server logs.")


async def polling_error(update, context):
    # Raw exception messages and httpx request logs can contain bot tokens.
    error = context.error
    log.error("Telegram update failure: %s", type(error).__name__)
    if isinstance(error, (Conflict, InvalidToken)) or (update is None and isinstance(error, Forbidden)):
        context.application.bot_data['runtime_exit_code'] = 78
        context.application.stop_running()


def build_application(token):
    application = ApplicationBuilder().token(token).post_init(verify_identity).build()
    application.add_handler(CommandHandler("backup", manual_backup_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(telegram_handler, pattern=r"^sr:"))
    application.add_handler(MessageHandler(filters.TEXT, telegram_handler))
    application.add_error_handler(polling_error)
    return application


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    allowed = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if not allowed or any(not value.strip().isdecimal() for value in allowed.split(',')):
        raise SystemExit("TELEGRAM_ALLOWED_USER_IDS is required (deny by default)")
    db = Path(os.getenv("BOT_DB_PATH", "bot_sessions.db"))
    if db.exists() and not verify_database_integrity(db):
        raise SystemExit("Existing session database failed integrity validation")
    application = build_application(token)
    lock = Path(os.getenv('TELEGRAM_LOCK_PATH', str(db) + '.poller.lock'))
    try:
        with polling_lock(lock):
            log.info("Starting single-consumer polling")
            application.run_polling(allowed_updates=["message", "callback_query"],
                                    bootstrap_retries=0, drop_pending_updates=False)
    except (Conflict, InvalidToken, Forbidden, RuntimeError):
        log.error('Telegram startup conflict or invalid configuration; listener stopped')
        return 78
    return application.bot_data.get('runtime_exit_code', 0)


if __name__ == "__main__":
    sys.exit(main())
