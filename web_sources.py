"""Web-wide open ebook sources, merged into msasoup search (key-free).

Sources:
  * Project Gutenberg (gutenberg.org) — full search with a browser UA
    (bot-gated otherwise); every ebook is public domain -> CC gate passes
    on licenseurl for the IA-hosted copies; direct /ebooks/<id>.epub or
    .txt downloads.
  * Open Library (openlibrary.org/search.json) — official JSON API;
    candidates are license-gated via agent.licensed() on their
    archive.org metadata (fail closed, same standard as the IA path).

Deliverable URLs pass ebook_search_pipeline.candidate_url (approved hosts
already include gutenberg.org + standardebooks.org; .epub/.txt suffixes
are accepted for the web path).
"""
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from typing import Protocol
from urllib.parse import quote

import requests


class _Http(Protocol):
    """Minimal duck-typed HTTP client (requests module or a test fake)."""
    def get(self, url, **kwargs): ...


class _Response(Protocol):
    text: str
    status_code: int
    def json(self): ...
    def raise_for_status(self): ...

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
GUTENBERG_OPDS = "https://m.gutenberg.org/ebooks/search.opds/"
GUTENBERG_EBOOK = "https://www.gutenberg.org/ebooks/"
OL_SEARCH = "https://openlibrary.org/search.json"
OPDS_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
OPDS_ID = re.compile(r"<id>https://www\.gutenberg\.org/ebooks/(\d+)\.opds</id>")
OPDS_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
OPDS_AUTHOR = re.compile(r'<content type="text">(.*?)</content>', re.S)
MAX_PER_SOURCE = 10


def _book(title, author, url, source):
    return {"id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
            "title": str(title)[:180],
            "author": str(author)[:120],
            "source_url": url,
            "source": source}


def gutenberg_search(query, *, client: _Http = requests,
                     max_results=MAX_PER_SOURCE):
    """Gutenberg catalog search via its OPDS (Atom) feed. Public domain only,
    so every result is openly licensed by definition. Returns each hit with a
    *direct* .epub file URL (Gutenberg's predictable per-ebook endpoint) so
    results satisfy the pipeline's candidate_url gate and are directly
    deliverable. Raises on network/parse failure."""
    if not query or not query.strip():
        return []
    response = client.get(
        GUTENBERG_OPDS,
        params={"query": query[:200]},
        headers={"User-Agent": BROWSER_UA, "Accept": "application/atom+xml"},
        timeout=(5, 25))
    response.raise_for_status()
    seen, out = set(), []
    for entry in OPDS_ENTRY.findall(response.text):
        num = OPDS_ID.search(entry)
        if not num or num.group(1) in seen:
            continue
        seen.add(num.group(1))
        title = OPDS_TITLE.search(entry)
        author = OPDS_AUTHOR.search(entry)
        author_text = unescape(author.group(1)).strip() if author else ""
        if "download" in author_text.lower():
            author_text = ""  # feed put a count, not an author
        out.append(_book(
            unescape(title.group(1)).strip() if title else "Ebook " + num.group(1),
            author_text or "Unknown",
            GUTENBERG_EBOOK + num.group(1) + ".epub", "gutenberg"))
        if len(out) >= max_results:
            break
    return out


def openlibrary_search(query, *, client: _Http = requests,
                     max_results=MAX_PER_SOURCE, rights_checker=None):
    """Open Library search -> CC-gated (fail closed) books with an
    archive.org download link. Rights check defaults to agent.licensed."""
    if not query or not query.strip():
        return []
    response = client.get(
        OL_SEARCH,
        params={"q": query[:200], "limit": "30",
                "fields": "key,title,author_name,ebook_access,ia"},
        timeout=(5, 25))
    response.raise_for_status()
    docs = response.json().get("docs", [])
    checker = rights_checker
    if checker is None:
        from agent import licensed  # fail-closed standard, same as IA path
        checker = licensed
    seen, out = set(), []

    def _check(doc):
        title = str(doc.get("title") or "Untitled")
        author = ", ".join(doc.get("author_name", []) or []) or "Unknown"
        for identifier in (doc.get("ia") or [])[:2]:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", str(identifier)):
                continue
            try:
                meta = client.get("https://archive.org/metadata/" + identifier,
                                  timeout=(5, 25))
                meta.raise_for_status()
                metadata = meta.json()
            except (requests.RequestException, ValueError, TypeError):
                continue
            if not checker(metadata):
                continue
            filename = None
            for entry in metadata.get("files", []):
                name = str(entry.get("name", ""))
                if name.lower().endswith((".epub", ".pdf")) and "/" not in name:
                    filename = name
                    break
            if not filename:
                continue
            url = ("https://archive.org/download/" + identifier + "/"
                   + quote(filename))
            return _book(title, author, url, "openlibrary")
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        for book in pool.map(_check, docs):
            if book is None:
                continue
            if book["source_url"] in seen:
                continue
            seen.add(book["source_url"])
            out.append(book)
            if len(out) >= max_results:
                break
    return out


def web_search(query, *, client: _Http = requests,
               rights_checker=None, max_results=MAX_PER_SOURCE):
    """Merge all web sources, dedupe by source_url. One failing source is
    skipped (the others still deliver); no sources -> []."""
    if client is None:
        return []
    found = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(gutenberg_search, query, client=client,
                        max_results=max_results),
            pool.submit(openlibrary_search, query, client=client,
                        rights_checker=rights_checker,
                        max_results=max_results),
        ]
        for future in futures:
            try:
                found.extend(future.result())
            except (requests.RequestException, ValueError, TypeError,
                    KeyError):
                pass
    books, seen = [], set()
    for book in found:
        if book["source_url"] in seen:
            continue
        seen.add(book["source_url"])
        books.append(book)
    return books
