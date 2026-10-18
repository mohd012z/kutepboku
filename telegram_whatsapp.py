"""Telegram inline buttons and callback handlers for msasoup WhatsApp sharing.

Requires a running Telegram update processor. Does not create one automatically.
"""
import os
import re
from whatsapp_gateway import share_link, valid_public_url

BOOK_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def authorized_user(user_id: int, *, environ=None) -> bool:
    env = os.environ if environ is None else environ
    allowed = {part.strip() for part in env.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if part.strip()}
    return str(user_id) in allowed


def book_keyboard(book_id: str, title: str, source_url: str) -> dict:
    """Return a Telegram inline keyboard, with a genuine WhatsApp share URL."""
    if not BOOK_KEY.fullmatch(book_id) or not valid_public_url(source_url):
        raise ValueError("Invalid book metadata")
    return {"inline_keyboard": [
        [{"text": "📖 Book details", "callback_data": "book:" + book_id}],
        [{"text": "📲 Share to WhatsApp", "url": share_link(title, source_url)}],
        [{"text": "📤 Request WhatsApp delivery", "callback_data": "wa:" + book_id}],
    ]}


def process_callback(callback: dict, *, book_lookup, request_store, environ=None) -> dict:
    """Authorize callback, then create a pending request, never send immediately."""
    user = callback.get("from") or {}
    if not authorized_user(user.get("id"), environ=environ):
        return {"ok": False, "text": "Not authorized"}
    data = callback.get("data", "")
    if not data.startswith("wa:") or not BOOK_KEY.fullmatch(data[3:]):
        return {"ok": False, "text": "Unsupported request"}
    book = book_lookup(data[3:])
    if not book or not valid_public_url(book.get("source_url", "")):
        return {"ok": False, "text": "Book unavailable"}
    request_id = request_store(user["id"], data[3:])
    return {"ok": True, "text": "Request " + str(request_id) +
            " created. Recipient consent and explicit confirmation are required before sending."}
