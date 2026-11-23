"""Verified search adapter: key-free Internet Archive + web-wide open
ebook sources (Gutenberg, Open Library), team-LLM relevance screening.
The legacy Google/Gemini path is retained for tests/optional use."""
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
import web_sources


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
    """Default search: key-free, web-wide discovery (Internet Archive +
    Project Gutenberg + Open Library) with team-LLM (OpenAI-compatible)
    relevance screening. No Google credentials required.

    Licensing stays fail closed per source: IA candidates must carry an
    explicit CC licenseurl; Gutenberg is public domain by definition;
    Open Library candidates pass the same CC gate as IA. Runs off the
    event loop; a failing source is skipped, the rest still deliver.
    """

    def _run():
        candidates, seen = [], set()
        ia = openlicensed_search(
            query,
            rights_checker=openlicensed_rights_checker,
            relevance_checker=None,  # screen the merged list in one LLM call
            max_results=15,
        )
        for book in ia:
            if book["source_url"] not in seen:
                seen.add(book["source_url"])
                candidates.append(book)
        for book in web_sources.web_search(query, max_results=15):
            if book["source_url"] not in seen:
                seen.add(book["source_url"])
                candidates.append(book)
        if not candidates:
            return []
        indices = llm_relevance_indices(query, [b["title"] for b in candidates])
        keep = (indices if indices is not None
                else set(range(1, len(candidates) + 1)))
        results = [b for i, b in enumerate(candidates, 1) if i in keep]
        return results[:20]

    return await asyncio.to_thread(_run)


async def google_verified_search(query):
    """Legacy search: Google Custom Search + Gemini. Requires GOOGLE_API_KEY
    and SEARCH_ENGINE_ID (and GEMINI_API_KEY for relevance). Retained for
    compatibility and its tests."""
    return await asyncio.to_thread(
        dynamic_ebook_search, query, rights_checker=archive_rights_checker, max_results=15
    )
