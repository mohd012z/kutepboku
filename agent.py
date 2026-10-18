"""msasoup: discover openly licensed books and deliver them to Telegram."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
from urllib.parse import urljoin, urlparse

import requests

BOT_NAME = "mysoupsearchbot"
MAX_BYTES = 20 * 1024 * 1024
LICENSES = ("creativecommons.org/licenses/by/", "creativecommons.org/licenses/by-sa/",
            "creativecommons.org/publicdomain/zero/", "creativecommons.org/publicdomain/mark/")


def safe_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (OSError, ValueError):
        return False


def get(session, url, **kwargs):
    for _ in range(5):
        if not safe_url(url):
            raise ValueError("Unsafe download URL")
        response = session.get(url, timeout=(5, 25), allow_redirects=False, **kwargs)
        if response.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, response.headers.get("Location", ""))
            response.close()
            kwargs.pop("params", None)
            continue
        response.raise_for_status()
        return response
    raise ValueError("Too many redirects")


def verify_bot(session, token):
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token or ""):
        raise ValueError("Missing or malformed TELEGRAM_BOT_TOKEN")
    try:
        response = session.get("https://api.telegram.org/bot" + token + "/getMe",
                               timeout=(5, 10), allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError("Telegram authentication rejected (HTTP %d)" % response.status_code)
        payload = response.json()
        bot = payload.get("result") or {}
        if not payload.get("ok") or not bot.get("is_bot") or bot.get("username", "").lower() != BOT_NAME:
            raise RuntimeError("Telegram bot identity mismatch")
        return bot
    except requests.RequestException:
        raise RuntimeError("Telegram authentication connection failed") from None


def licensed(metadata):
    license_url = str(metadata.get("metadata", {}).get("licenseurl", "")).lower()
    return license_url.startswith("https://") and any(
        license_url.startswith("https://" + item) for item in LICENSES
    )


def download(session, url):
    response = get(session, url, stream=True)
    try:
        result = bytearray()
        for chunk in response.iter_content(65536):
            result.extend(chunk)
            if len(result) > MAX_BYTES:
                raise ValueError("File exceeds size limit")
        data = bytes(result)
        if len(data) < 1024:
            raise ValueError("Document too small")
        if data.startswith(b"%PDF-"):
            return "pdf", data
        if data.startswith(b"PK\\x03\\x04") and b"mimetypeapplication/epub+zip" in data[:200]:
            return "epub", data
        raise ValueError("Invalid PDF/EPUB signature")
    finally:
        response.close()


def discover(session, query):
    response = get(session, "https://openlibrary.org/search.json",
                   params={"q": query, "limit": 20,
                           "fields": "key,title,public_scan_b,ia"})
    try:
        return response.json().get("docs", [])
    finally:
        response.close()


def send(session, token, chat, name, data, caption):
    response = session.post("https://api.telegram.org/bot" + token + "/sendDocument",
                            data={"chat_id": chat, "caption": caption[:1024]},
                            files={"document": (name, data)}, timeout=(10, 60))
    if response.status_code != 200 or not response.json().get("ok"):
        raise RuntimeError("Telegram delivery failed (HTTP %d)" % response.status_code)


def run():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat:
        raise ValueError("Missing TELEGRAM_CHAT_ID")
    session = requests.Session()
    session.trust_env = False
    bot = verify_bot(session, token)
    print("Verified Telegram bot @%s (ID %s)" % (bot["username"], bot["id"]))
    state = Path("state/history.json")
    history = json.loads(state.read_text()) if state.exists() else []
    delivered = set(history)
    query = os.environ.get("SCOUT_QUERY", "python programming")
    for book in discover(session, query):
        if not book.get("public_scan_b"):
            continue
        for identifier in book.get("ia", [])[:2]:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", identifier):
                continue
            meta_response = get(session, "https://archive.org/metadata/" + identifier)
            try:
                metadata = meta_response.json()
            finally:
                meta_response.close()
            if not licensed(metadata):
                continue
            for entry in metadata.get("files", []):
                name = entry.get("name", "")
                if not name.lower().endswith((".pdf", ".epub")) or "/" in name:
                    continue
                url = "https://archive.org/download/" + identifier + "/" + requests.utils.requote_uri(name)
                try:
                    ext, content = download(session, url)
                except (ValueError, requests.RequestException):
                    continue
                digest = hashlib.sha256(content).hexdigest()
                if digest in delivered:
                    continue
                send(session, token, chat, "book." + ext, content,
                     str(book.get("title", "Open eBook")) + "\\n" + url)
                delivered.add(digest)
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text(json.dumps(sorted(delivered), indent=2) + "\\n")
                print("Delivered:", book.get("title", "Open eBook"))
                return
    print("No new licensed document found")


if __name__ == "__main__":
    run()
