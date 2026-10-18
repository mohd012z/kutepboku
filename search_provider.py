"""Verified search adapter: Google/Gemini discovery plus independent IA licensing."""
import asyncio
import re
from urllib.parse import unquote, urlparse

import requests

from agent import get, licensed
from ebook_search_pipeline import dynamic_ebook_search


def archive_rights_checker(url, item, *, session=None):
    """Only explicitly licensed Internet Archive files pass; fail closed."""
    parsed = urlparse(url)
    if parsed.hostname != "archive.org" or not parsed.path.startswith("/download/"):
        return False
    parts = parsed.path.split("/")
    if len(parts) != 4:
        return False
    identifier = unquote(parts[2])
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", identifier):
        return False
    session = session or requests.Session()
    try:
        response = get(session, "https://archive.org/metadata/" + identifier)
        try:
            metadata = response.json()
        finally:
            response.close()
        filename = unquote(parts[3])
        files = metadata.get("files", [])
        return licensed(metadata) and any(
            entry.get("name") == filename for entry in files if isinstance(entry, dict)
        )
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return False


async def verified_search(query):
    """Search off the event loop; do not expose unlicensed candidates."""
    return await asyncio.to_thread(
        dynamic_ebook_search, query, rights_checker=archive_rights_checker, max_results=15
    )
