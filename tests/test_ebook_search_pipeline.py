import unittest
from unittest.mock import Mock
from ebook_search_pipeline import candidate_url, dynamic_ebook_search, gemini_relevant


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


if __name__ == "__main__":
    unittest.main()
