import asyncio
import unittest
from unittest.mock import Mock, patch

import search_provider
from search_provider import archive_rights_checker, verified_search


class RightsTests(unittest.TestCase):
    def test_rejects_non_archive_link(self):
        self.assertFalse(archive_rights_checker("https://example.com/book.pdf", {}))

    def test_rejects_invalid_identifier(self):
        self.assertFalse(archive_rights_checker("https://archive.org/download/%2E%2E/book.pdf", {}))

    def test_requires_explicit_license(self):
        response = Mock()
        response.json.return_value = {
            "metadata": {},
            "files": [{"name": "book.pdf"}],
        }
        response.status_code = 200
        response.headers = {}
        session = Mock()
        session.get.return_value = response
        with patch("agent.safe_url", return_value=True):
            self.assertFalse(archive_rights_checker(
                "https://archive.org/download/bookid/book.pdf", {}, session=session
            ))


class VerifiedSearchMergedTests(unittest.TestCase):
    """verified_search merges IA + web sources and screens once with the LLM."""

    def _ia_book(self, title, url):
        return {"id": "ia-" + title, "title": title, "author": "Unknown",
                "source_url": url}

    def _web_book(self, title, url):
        return {"id": "web-" + title, "title": title, "author": "Someone",
                "source_url": url, "source": "gutenberg"}

    def test_merges_and_dedupes_by_url(self):
        ia = [self._ia_book("A", "https://archive.org/download/x/a.epub"),
              self._ia_book("B", "https://archive.org/download/y/b.epub")]
        web = [self._web_book("B", "https://archive.org/download/y/b.epub"),
               self._web_book("C", "https://www.gutenberg.org/ebooks/1.epub")]
        with patch("search_provider.openlicensed_search", return_value=ia), \
             patch("search_provider.web_sources.web_search", return_value=web), \
             patch("search_provider.llm_relevance_indices",
                   return_value={1, 3}) as llm:
            got = asyncio.run(verified_search("t"))
        llm.assert_called_once()
        titles = llm.call_args[0][1]
        self.assertEqual(titles, ["A", "B", "C"])
        self.assertEqual([b["title"] for b in got], ["A", "C"])

    def test_llm_unavailable_keeps_all(self):
        ia = [self._ia_book("A", "https://archive.org/download/x/a.epub")]
        web = [self._web_book("C", "https://www.gutenberg.org/ebooks/1.epub")]
        with patch("search_provider.openlicensed_search", return_value=ia), \
             patch("search_provider.web_sources.web_search", return_value=web), \
             patch("search_provider.llm_relevance_indices", return_value=None):
            got = asyncio.run(verified_search("t"))
        self.assertEqual([b["title"] for b in got], ["A", "C"])

    def test_all_sources_empty(self):
        with patch("search_provider.openlicensed_search", return_value=[]), \
             patch("search_provider.web_sources.web_search", return_value=[]), \
             patch("search_provider.llm_relevance_indices") as llm:
            got = asyncio.run(verified_search("t"))
        self.assertEqual(got, [])
        llm.assert_not_called()
