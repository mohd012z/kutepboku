"""Native Telegram inline-keyboard UI for msasoup delivery selection.

This module builds messages and validates callbacks; it does not run a bot.
"""
import re

from telegram_whatsapp import authorized_user
from whatsapp_gateway import share_link, valid_public_url

BOOK_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DESTINATIONS = {"tg": "Telegram", "email": "Email", "wa": "WhatsApp"}


def menu():
    return {"text": "📚 msasoup · eBook Assistant\nChoose an action:",
            "reply_markup": {"inline_keyboard": [
                [{"text": "🔎 Find eBooks", "callback_data": "ui:search"}],
                [{"text": "📚 My Library", "callback_data": "ui:library"}],
                [{"text": "⚙️ Delivery Settings", "callback_data": "ui:settings"}],
            ]}}


def book_card(book_id, title, author, source_url):
    if not BOOK_ID.fullmatch(book_id) or not valid_public_url(source_url):
        raise ValueError("Invalid book record")
    return {"text": "📖 " + title[:180] + "\n✍️ " + author[:120] +
            "\n🔗 " + source_url + "\n\nCheck license and available formats before delivery.",
            "reply_markup": {"inline_keyboard": [
                [{"text": "📤 Send / Share", "callback_data": "ui:deliver:" + book_id}],
                [{"text": "🔙 Home", "callback_data": "ui:home"}],
            ]}}


def destination_menu(book_id, title, source_url):
    if not BOOK_ID.fullmatch(book_id) or not valid_public_url(source_url):
        raise ValueError("Invalid book record")
    return {"text": "📤 Delivery Center\n" + title[:180] +
            "\n\nChoose where to receive or share this book:",
            "reply_markup": {"inline_keyboard": [
                [{"text": "✈️ Telegram", "callback_data": "ui:choose:tg:" + book_id}],
                [{"text": "✉️ Email", "callback_data": "ui:choose:email:" + book_id}],
                [{"text": "💬 WhatsApp Share", "url": share_link(title, source_url)}],
                [{"text": "💬 WhatsApp Auto (opt-in)", "callback_data": "ui:choose:wa:" + book_id}],
                [{"text": "🔙 Book details", "callback_data": "ui:book:" + book_id}],
            ]}}


def confirmation(book_id, destination):
    if not BOOK_ID.fullmatch(book_id) or destination not in DESTINATIONS:
        raise ValueError("Invalid delivery selection")
    label = DESTINATIONS[destination]
    note = {
        "tg": "Sends to your authorized Telegram chat.",
        "email": "Requires a verified email address and configured email service.",
        "wa": "Requires recipient opt-in and configured WhatsApp Business API.",
    }[destination]
    return {"text": "🔐 Confirm delivery\nDestination: " + label +
            "\n" + note + "\n\nNo message will be sent until confirmed.",
            "reply_markup": {"inline_keyboard": [
                [{"text": "✅ Confirm request", "callback_data": "ui:confirm:" + destination + ":" + book_id}],
                [{"text": "🔙 Change destination", "callback_data": "ui:deliver:" + book_id}],
            ]}}


def route_callback(callback, *, book_lookup, enqueue_request, environ=None):
    """Return UI response. Confirm creates a pending job, never sends directly.

    enqueue_request must enforce durable authorization, recipient verification,
    opt-in, idempotency and downstream delivery policy.
    """
    user_id = (callback.get("from") or {}).get("id")
    if not authorized_user(user_id, environ=environ):
        return {"text": "⛔ Access denied", "reply_markup": {"inline_keyboard": []}}
    data = callback.get("data", "")
    if data in ("ui:home", "ui:search", "ui:library", "ui:settings"):
        if data == "ui:home":
            return menu()
        return {"text": {"ui:search": "🔎 Send a title, author or topic to search.",
                         "ui:library": "📚 Library indexing is not connected yet.",
                         "ui:settings": "⚙️ Delivery settings are not configured yet."}[data]}
    parts = data.split(":")
    if len(parts) == 3 and parts[0] == "ui" and parts[1] in ("book", "deliver"):
        book_id = parts[2]
        if not BOOK_ID.fullmatch(book_id):
            return {"text": "Invalid book"}
        book = book_lookup(book_id)
        if not book:
            return {"text": "Book not found"}
        if parts[1] == "book":
            return book_card(book_id, book["title"], book.get("author", "Unknown"), book["source_url"])
        return destination_menu(book_id, book["title"], book["source_url"])
    if len(parts) == 4 and parts[0] == "ui" and parts[1] in ("choose", "confirm"):
        destination, book_id = parts[2:]
        if destination not in DESTINATIONS or not BOOK_ID.fullmatch(book_id):
            return {"text": "Invalid selection"}
        book = book_lookup(book_id)
        if not book or not valid_public_url(book.get("source_url", "")):
            return {"text": "Book unavailable"}
        if parts[1] == "choose":
            return confirmation(book_id, destination)
        job_id = enqueue_request(user_id, destination, book_id)
        return {"text": "🕒 Delivery request " + str(job_id) +
                " queued for authorization and destination verification. Not yet sent."}
    return {"text": "Unsupported action"}
