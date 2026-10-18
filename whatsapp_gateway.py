"""WhatsApp sharing and opt-in Cloud API delivery for msasoup.

Never deliver without an explicit user confirmation and recorded recipient consent.
"""
from dataclasses import dataclass
import os
import re
from urllib.parse import urlencode, urlparse

import requests

PHONE = re.compile(r"^[1-9][0-9]{7,14}$")
BOOK_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def valid_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in {
            "openlibrary.org", "archive.org", "www.gutenberg.org",
            "standardebooks.org"
        } and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except ValueError:
        return False


def normalize_phone(value: str) -> str:
    number = re.sub(r"[ +()-]", "", value)
    if not PHONE.fullmatch(number):
        raise ValueError("Use an international phone number without the plus sign")
    return number


def share_link(title: str, book_url: str) -> str:
    """WhatsApp click-to-chat opens a draft; user must press Send."""
    if not valid_public_url(book_url):
        raise ValueError("Sharing requires an authorized HTTPS source link")
    message = "Book: " + title[:160] + "\nSource: " + book_url
    return "https://wa.me/?" + urlencode({"text": message})


@dataclass(frozen=True)
class DeliveryRequest:
    book_id: str
    title: str
    recipient: str
    document_url: str
    consent: bool
    confirmed: bool


def deliver_document(req: DeliveryRequest, *, session=None, environ=None) -> str:
    """Explicitly confirmed WhatsApp Business Cloud API document delivery.

    Callers must authenticate the requesting Telegram user and obtain consent
    before constructing DeliveryRequest. This function rejects unconfirmed sends.
    """
    env = os.environ if environ is None else environ
    if not req.consent or not req.confirmed:
        raise PermissionError("Recipient opt-in and sender confirmation required")
    if not BOOK_ID.fullmatch(req.book_id):
        raise ValueError("Invalid book ID")
    phone = normalize_phone(req.recipient)
    if not valid_public_url(req.document_url):
        raise ValueError("Only approved source URLs can be sent")
    if env.get("WHATSAPP_DELIVERY_ENABLED") != "true":
        raise RuntimeError("WhatsApp Business delivery is disabled")
    token = env.get("WHATSAPP_ACCESS_TOKEN")
    sender = env.get("WHATSAPP_PHONE_NUMBER_ID")
    version = env.get("WHATSAPP_GRAPH_VERSION", "v23.0")
    if not token or not sender or not re.fullmatch(r"[0-9]{5,30}", sender):
        raise RuntimeError("Missing WhatsApp Business API configuration")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid Graph API version")
    client = session or requests
    endpoint = "https://graph.facebook.com/" + version + "/" + sender + "/messages"
    payload = {
        "messaging_product": "whatsapp", "to": phone, "type": "document",
        "document": {"link": req.document_url, "filename": "msasoup-book.pdf"},
    }
    try:
        response = client.post(endpoint, json=payload,
                               headers={"Authorization": "Bearer " + token},
                               timeout=(5, 25))
        if response.status_code not in (200, 201):
            raise RuntimeError("WhatsApp API rejected delivery (HTTP %s)" % response.status_code)
        data = response.json()
        messages = data.get("messages") or []
        if not messages or not messages[0].get("id"):
            raise RuntimeError("WhatsApp API returned no message ID")
        return str(messages[0]["id"])
    except requests.RequestException:
        raise RuntimeError("WhatsApp API request failed") from None
