"""Verified search adapter: Google/Gemini discovery plus independent IA licensing."""
import asyncio
import re
from urllib.parse import unquote, urlparse

import requests

from agent import get, licensed
from ebook_search_pipeline import (
    dynamic_ebook_search,
    llm_relevance_indices,
    openlicensed_search,
)


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


def openlicensed_rights_checker(identifier, metadata):
    """Fail-closed gate for the key-free path: Internet Archive metadata must
    carry an explicit open license (agent.licensed) and expose a distributable
    PDF/EPUB. Borrowed / print-disabled scans have no licenseurl and are
    rejected."""
    if not isinstance(metadata, dict) or not licensed(metadata):
        return False
    return any(
        isinstance(entry, dict) and str(entry.get("name", "")).lower().endswith((".pdf", ".epub"))
        for entry in metadata.get("files", [])
    )


async def verified_search(query):
    """Default search: key-free Internet Archive discovery + team-LLM
    (OpenAI-compatible) relevance screening. No Google credentials required.

    Runs off the event loop; unlicensed candidates are excluded before the LLM
    ever sees them.
    """

    def _run():
        return openlicensed_search(
            query,
            rights_checker=openlicensed_rights_checker,
            relevance_checker=lambda topic, titles: llm_relevance_indices(topic, titles),
            max_results=15,
        )

    return await asyncio.to_thread(_run)


async def google_verified_search(query):
    """Legacy search: Google Custom Search + Gemini. Requires GOOGLE_API_KEY
    and SEARCH_ENGINE_ID (and GEMINI_API_KEY for relevance). Retained for
    compatibility and its tests."""
    return await asyncio.to_thread(
        dynamic_ebook_search, query, rights_checker=archive_rights_checker, max_results=15
    )
