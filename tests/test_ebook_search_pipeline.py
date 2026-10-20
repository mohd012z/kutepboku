import unittest
from unittest.mock import Mock
from ebook_search_pipeline import (
    candidate_url, dynamic_ebook_search, gemini_relevant,
    llm_relevance_indices, openlicensed_search,
)


class SearchTests(unittest.TestCase):
    def test_only_approved_https_file_urls(self):
        self.assertTrue(candidate_url("https://archive.org/download/sample/book.epub"))
        self.assertFalse(candidate_url("https://example.org/book.epub"))
        self.assertFalse(candidate_url("http://archive.org/download/sample/book.pdf"))
        self.assertFalse(candidate_url("https://archive.org/details/book"))

    def test_no_credentials_returns_empty(self):
        self.assertEqual(dynamic_ebook_search("python", api_key="", search_engine_id=""), [])

    def test_no_rights_checker_fails_closed(self):
        client = Mock()
        client.get.return_value.json.return_value = {"items": [
            {"link": "https://archive.org/download/x/a.pdf", "title": "Python"}]}
        self.assertEqual(dynamic_ebook_search("python", client=client,
            relevance_checker=lambda *a: True, api_key="k", search_engine_id="cx"), [])

    def test_relevant_and_rights_approved(self):
        client = Mock()
        client.get.return_value.json.return_value = {"items": [
            {"link": "https://archive.org/download/x/a.pdf", "title": "Python"},
            {"link": "https://archive.org/download/x/a.pdf", "title": "Duplicate"}]}
        results = dynamic_ebook_search("python", client=client,
            relevance_checker=lambda *a: True,
            rights_checker=lambda url, item: True,
            api_key="k", search_engine_id="cx", max_results=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["id"]), 16)

    def test_relevance_failure_rejects(self):
        client = Mock()
        client.get.return_value.json.return_value = {"items": [
            {"link": "https://archive.org/download/x/a.pdf", "title": "Python"}]}
        results = dynamic_ebook_search("python", client=client,
            relevance_checker=lambda *a: None,
            rights_checker=lambda *a: True,
            api_key="k", search_engine_id="cx", max_results=1)
        self.assertEqual(results, [])

    def test_gemini_boolean_only(self):
        client = Mock()
        client.post.return_value.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"relevant":true}'}]}}]}
        self.assertIs(gemini_relevant("python", "Python", "Tutorial",
                                     client=client, api_key="test"), True)


def _meta_response(identifier, licenseurl, filenames):
    """A Mock .json() shaped like archive.org/metadata/<id>."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "metadata": {"licenseurl": licenseurl, "title": "T"},
        "files": [{"name": n} for n in filenames],
    }
    return response


def _search_response(docs):
    """A Mock .json() shaped like archive.org/advancedsearch (output=json)."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"response": {"numFound": len(docs), "docs": docs}}
    return response


def identifier_from_url(url):
    return url.split("archive.org/metadata/")[-1]


class KeyFreeDiscoveryTests(unittest.TestCase):
    def test_llm_relevance_indices_parses_int_list(self):
        client = Mock()
        client.post.return_value.json.return_value = {"choices": [
            {"message": {"content": '{"relevant": [1, 3]}'}}]}
        got = llm_relevance_indices("python", ["A", "B", "C"],
                                   client=client, base_url="http://x", api_key="k")
        self.assertEqual(got, {1, 3})

    def test_llm_relevance_indices_none_without_key(self):
        self.assertIsNone(llm_relevance_indices("python", ["A"],
                                                base_url="http://x", api_key=""))

    def test_llm_relevance_indices_none_on_malformed(self):
        client = Mock()
        client.post.return_value.json.return_value = {"choices": [
            {"message": {"content": "not json"}}]}
        self.assertIsNone(llm_relevance_indices("python", ["A"],
                                                client=client, base_url="http://x", api_key="k"))

    def test_openlicensed_empty_query(self):
        self.assertEqual(openlicensed_search("", rights_checker=lambda *a: True), [])

    def test_openlicensed_no_candidates(self):
        client = Mock()
        client.get.return_value = _search_response([])
        self.assertEqual(openlicensed_search("python", client=client,
                                             rights_checker=lambda *a: True), [])

    def test_openlicensed_requires_rights_and_llm(self):
        docs = [{"identifier": "bookid1", "title": "Python Basics"},
                {"identifier": "bookid2", "title": "Unrelated"}]
        meta = {
            "bookid1": _meta_response("bookid1",
                                      "https://creativecommons.org/licenses/by/4.0/", ["bookid1.epub"]),
            "bookid2": _meta_response("bookid2",
                                      "https://creativecommons.org/licenses/by/4.0/", ["bookid2.pdf"]),
        }

        def dispatch(url, **kw):
            if "advancedsearch" in url:
                return _search_response(docs)
            return meta[identifier_from_url(url)]

        client = Mock()
        client.get.side_effect = dispatch
        # LLM keeps only index 1.
        results = openlicensed_search("python", client=client,
                                      rights_checker=lambda *a: True,
                                      relevance_checker=lambda topic, titles: {1},
                                      max_results=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_url"],
                         "https://archive.org/download/bookid1/bookid1.epub")
        self.assertEqual(len(results[0]["id"]), 16)

    def test_openlicensed_no_rights_fails_closed(self):
        docs = [{"identifier": "bookid1", "title": "Python Basics"}]

        def dispatch(url, **kw):
            if "advancedsearch" in url:
                return _search_response(docs)
            return _meta_response("bookid1",
                                  "https://creativecommons.org/licenses/by/4.0/", ["bookid1.epub"])

        client = Mock()
        client.get.side_effect = dispatch
        results = openlicensed_search("python", client=client,
                                      rights_checker=lambda *a: False,
                                      relevance_checker=lambda *a: {1})
        self.assertEqual(results, [])

    def test_openlicensed_bad_identifier_skipped(self):
        docs = [{"identifier": "../x", "title": "Bad"}]
        client = Mock()
        client.get.return_value = _search_response(docs)
        # identifier rejected before any metadata fetch
        self.assertEqual(openlicensed_search("python", client=client,
                                             rights_checker=lambda *a: True,
                                             relevance_checker=None), [])


if __name__ == "__main__":
    unittest.main()
