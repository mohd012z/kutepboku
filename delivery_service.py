"""Delivery service for authorized public-domain/open-license eBooks.

All dispatch calls require server-side authorization and verified recipients.
This module does not make recipient verification decisions.
"""
from contextlib import contextmanager
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import re
import smtplib
import ssl

import requests

from whatsapp_gateway import share_link

MAX_BYTES = 20 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def verified_book(book):
    return (isinstance(book, dict) and book.get("rights_verified") is True
            and book.get("distribution_allowed") is True
            and isinstance(book.get("title"), str)
            and isinstance(book.get("source_url"), str))


def validate_file(path):
    data = Path(path).read_bytes()
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Invalid document size")
    if data.startswith(b"%PDF-"):
        return "application/pdf", "book.pdf"
    if data.startswith(b"PK\x03\x04") and b"mimetypeapplication/epub+zip" in data[:256]:
        return "application/epub+zip", "book.epub"
    raise ValueError("Unsupported document format")


@contextmanager
def temporary_book(book, *, downloader):
    """Use a vetted downloader that enforces host/IP/redirect and size policies.

    downloader(url, destination, max_bytes) must raise on errors.
    """
    if not verified_book(book):
        raise PermissionError("Distribution rights not verified")
    with TemporaryDirectory(prefix="msasoup-") as directory:
        path = Path(directory) / "document"
        downloader(book["source_url"], str(path), MAX_BYTES)
        mime, name = validate_file(path)
        yield str(path), mime, name


def deliver_telegram(chat_id, path, title, *, verified_chat, client=requests, token=None):
    if not verified_chat or not isinstance(chat_id, int):
        raise PermissionError("Telegram chat is not verified")
    secret = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN")
    if not secret:
        raise RuntimeError("Telegram bot token missing")
    with open(path, "rb") as document:
        response = client.post("https://api.telegram.org/bot" + secret + "/sendDocument",
                               data={"chat_id": chat_id, "caption": ("📚 " + title)[:1024]},
                               files={"document": document}, timeout=(5, 60))
    response.raise_for_status()
    payload = response.json()
    if payload.get("ok") is not True:
        raise RuntimeError("Telegram rejected document")
    return payload.get("result", {}).get("message_id")


def deliver_email(recipient, path, title, *, verified_recipient, smtp_factory=smtplib.SMTP,
                  environ=None):
    env = os.environ if environ is None else environ
    if not verified_recipient or not isinstance(recipient, str) or not EMAIL_RE.fullmatch(recipient):
        raise PermissionError("Email recipient is not verified")
    host = env.get("SMTP_SERVER")
    user = env.get("SMTP_USER")
    password = env.get("SMTP_PASSWORD")
    if not host or not user or not password:
        raise RuntimeError("SMTP credentials not configured")
    port = int(env.get("SMTP_PORT", "587"))
    mime, name = validate_file(path)
    msg = EmailMessage()
    msg["Subject"] = "Your requested eBook: " + title[:120].replace("\r", " ").replace("\n", " ")
    msg["From"] = user
    msg["To"] = recipient
    msg.set_content("Attached is the eBook you requested through msasoup.")
    major, minor = mime.split("/", 1)
    msg.add_attachment(Path(path).read_bytes(), maintype=major, subtype=minor, filename=name)
    with smtp_factory(host, port, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(user, password)
        server.send_message(msg)
    return True


def dispatch(book, channel, *, downloader=None, recipient=None, recipient_verified=False,
             sender_confirmed=False, telegram_chat=None, telegram_client=requests,
             smtp_factory=smtplib.SMTP, environ=None):
    """Send only after explicit user confirmation; caller must persist job outcome.

    WhatsApp share returns a user-initiated URL; it does not send a message.
    """
    if not verified_book(book):
        raise PermissionError("Distribution rights not verified")
    if not sender_confirmed:
        raise PermissionError("Sender confirmation required")
    if channel == "whatsapp_share":
        return {"status": "SHARE_READY", "url": share_link(book["title"], book["source_url"])}
    if channel not in ("telegram", "email"):
        raise ValueError("Unsupported channel")
    if not recipient_verified:
        raise PermissionError("Recipient verification required")
    if downloader is None:
        raise RuntimeError("Vetted downloader required")
    with temporary_book(book, downloader=downloader) as (path, _, _):
        if channel == "telegram":
            message_id = deliver_telegram(telegram_chat, path, book["title"],
                                          verified_chat=True, client=telegram_client,
                                          token=(environ or os.environ).get("TELEGRAM_BOT_TOKEN"))
            return {"status": "ACCEPTED", "message_id": message_id}
        deliver_email(recipient, path, book["title"], verified_recipient=True,
                      smtp_factory=smtp_factory, environ=environ)
        return {"status": "ACCEPTED"}
