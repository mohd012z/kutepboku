"""Tests for web_sources (Gutenberg OPDS + Open Library) and the merged
search_provider.verified_search path."""
import json
import unittest
from unittest import mock

import requests

import web_sources
from web_sources import (gutenberg_search, openlibrary_search, web_search)

OPDS_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Search results</title>
  <updated>2026-01-01T00:00:00Z</updated>
  <id>collection</id>
  {entries}
</feed>"""

ENTRY = """  <entry>
    <updated>2026-01-01T00:00:00Z</updated>
    <id>https://www.gutenberg.org/ebooks/{num}.opds</id>
    <title>{title}</title>
    <content type="text">{author}</content>
    <link type="application/atom+xml" rel="subsection" href="/ebooks/{num}.opds"/>
  </entry>"""


class FakeResponse:
    def __init__(self, text=None, payload=None, status=200):
        self._text = text
        self._payload = payload
        self.status_code = status

    @property
    def text(self):
        return self._text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %d" % self.status_code)


class FakeClient:
    """Maps URL (or URL+params) -> FakeResponse."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        params = kwargs.get("params") or {}
        key = (url, tuple(sorted(params.items())))
        plain = url
        for k in (key, plain):
            if k in self.routes:
                return self.routes[k]
        raise AssertionError("unexpected GET " + url)


class GutenbergSearchTests(unittest.TestCase):
    def _client(self, entries):
        feed = OPDS_TEMPLATE.format(entries="\n".join(entries))
        return FakeClient({
            (web_sources.GUTENBERG_OPDS,
             (("query", "machine learning"),)): FakeResponse(text=feed),
        })

    def test_parses_entries_with_direct_epub_urls(self):
        client = self._client([
            ENTRY.format(num=43, title="Jekyll &amp; Hyde", author="Stevenson"),
            ENTRY.format(num=42, title="Pride and Prejudice", author="Austen"),
        ])
        books = gutenberg_search("machine learning", client=client)
        self.assertEqual(len(books), 2)
        self.assertEqual(books[0]["title"], "Jekyll & Hyde")
        self.assertEqual(books[0]["author"], "Stevenson")
        self.assertEqual(books[0]["source_url"],
                         "https://www.gutenberg.org/ebooks/43.epub")
        self.assertEqual(books[0]["source"], "gutenberg")
        self.assertTrue(books[0]["id"])

    def test_download_count_is_not_an_author(self):
        client = self._client([
            ENTRY.format(num=66286, title="Self-Organizing", author="571 downloads"),
        ])
        books = gutenberg_search("machine learning", client=client)
        self.assertEqual(books[0]["author"], "Unknown")

    def test_dedupes_repeated_ids(self):
        client = self._client([
            ENTRY.format(num=1, title="A", author="x"),
            ENTRY.format(num=1, title="A again", author="x"),
            ENTRY.format(num=2, title="B", author="y"),
        ])
        books = gutenberg_search("machine learning", client=client)
        self.assertEqual([b["source_url"] for b in books],
                         ["https://www.gutenberg.org/ebooks/1.epub",
                          "https://www.gutenberg.org/ebooks/2.epub"])

    def test_respects_max_results(self):
        client = self._client([ENTRY.format(num=str(i), title="T", author="a")
                               for i in range(20)])
        books = gutenberg_search("machine learning", client=client,
                                 max_results=3)
        self.assertEqual(len(books), 3)

    def test_empty_query_no_request(self):
        client = FakeClient({})
        self.assertEqual(gutenberg_search("   ", client=client), [])
        self.assertEqual(client.calls, [])

    def test_network_failure_raises(self):
        def get(url, **kw):
            raise requests.ConnectionError("down")
        client = mock.Mock()
        client.get = get
        with self.assertRaises(requests.ConnectionError):
            gutenberg_search("x", client=client)


META_CC = {"metadata": {"licenseurl":
                        "https://creativecommons.org/licenses/by/4.0/"},
           "files": [{"name": "book.epub"}, {"name": "_cover.jpg"}]}
META_ND = {"metadata": {"licenseurl":
                        "https://creativecommons.org/licenses/by-nc/4.0/"},
           "files": [{"name": "book.epub"}]}
META_NONE = {"metadata": {}, "files": [{"name": "book.epub"}]}


class OpenLibrarySearchTests(unittest.TestCase):
    def _client(self, docs, metas):
        routes = {
            (web_sources.OL_SEARCH, (("fields",
                                      "key,title,author_name,ebook_access,ia"),
                                     ("limit", "30"), ("q", "q"))):
                FakeResponse(payload={"docs": docs}),
        }
        for identifier, meta in metas.items():
            routes["https://archive.org/metadata/" + identifier] = \
                FakeResponse(payload=meta)
        return FakeClient(routes)

    def test_cc_candidate_passes_with_download_link(self):
        client = self._client(
            [{"title": "Good Book", "author_name": ["Jane"],
              "ia": ["goodbook01jane"]}],
            {"goodbook01jane": META_CC})
        books = openlibrary_search("q", client=client)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["title"], "Good Book")
        self.assertEqual(books[0]["author"], "Jane")
        self.assertEqual(books[0]["source_url"],
                         "https://archive.org/download/goodbook01jane/book.epub")
        self.assertEqual(books[0]["source"], "openlibrary")

    def test_non_cc_and_unlicensed_fail_closed(self):
        client = self._client(
            [{"title": "NC", "author_name": [], "ia": ["ndbook"]},
             {"title": "NoLic", "author_name": [], "ia": ["nolicbook"]},
             {"title": "CC", "author_name": ["A"], "ia": ["ccbook"]}],
            {"ndbook": META_ND, "nolicbook": META_NONE, "ccbook": META_CC})
        books = openlibrary_search("q", client=client)
        self.assertEqual([b["title"] for b in books], ["CC"])

    def test_custom_rights_checker_used(self):
        client = self._client(
            [{"title": "X", "author_name": [], "ia": ["xbook"]}],
            {"xbook": META_ND})
        books = openlibrary_search("q", client=client,
                                   rights_checker=lambda m: True)
        self.assertEqual(len(books), 1)

    def test_bad_identifier_and_meta_failure_skip(self):
        client = self._client(
            [{"title": "Bad", "author_name": [], "ia": ["a b!" + "0" * 100]},
             {"title": "Ok", "author_name": [], "ia": ["okbook"]}],
            {"okbook": META_CC})
        books = openlibrary_search("q", client=client)
        self.assertEqual([b["title"] for b in books], ["Ok"])

    def test_empty_query(self):
        self.assertEqual(openlibrary_search("", client=FakeClient({})), [])


class WebSearchTests(unittest.TestCase):
    def test_merges_sources_and_dedupes(self):
        entries = [ENTRY.format(num=1, title="One", author="a")]
        feed = OPDS_TEMPLATE.format(entries="\n".join(entries))
        routes = {
            (web_sources.GUTENBERG_OPDS, (("query", "x"),)):
                FakeResponse(text=feed),
            (web_sources.OL_SEARCH, (("fields",
                                      "key,title,author_name,ebook_access,ia"),
                                     ("limit", "30"), ("q", "x"))):
                FakeResponse(payload={"docs": [
                    {"title": "Two", "author_name": ["b"], "ia": ["twobook"]},
                ]}),
            "https://archive.org/metadata/twobook": FakeResponse(payload=META_CC),
        }
        books = web_search("x", client=FakeClient(routes))
        self.assertEqual([b["source"] for b in books],
                         ["gutenberg", "openlibrary"])

    def test_one_source_down_still_delivers(self):
        feed = OPDS_TEMPLATE.format(entries=ENTRY.format(num=9, title="Nine",
                                                         author="a"))
        routes = {
            (web_sources.GUTENBERG_OPDS, (("query", "x"),)):
                FakeResponse(text=feed),
            (web_sources.OL_SEARCH, (("fields",
                                      "key,title,author_name,ebook_access,ia"),
                                     ("limit", "30"), ("q", "x"))):
                FakeResponse(payload=None, status=500),
        }
        books = web_search("x", client=FakeClient(routes))
        self.assertEqual([b["source"] for b in books], ["gutenberg"])

    def test_none_client(self):
        self.assertEqual(web_search("x", client=None), [])


if __name__ == "__main__":
    unittest.main()
