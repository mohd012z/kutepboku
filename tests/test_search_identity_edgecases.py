import unittest
from search_identity import normalize_query, book_identity, repo_identity

class SearchIdentityEdgeCases(unittest.TestCase):
    def test_preserve_technical_terms(self):
        self.assertNotEqual(normalize_query("search engine"),normalize_query("engine"))
        self.assertNotEqual(normalize_query("C--"),normalize_query("C++"))
    def test_distinct_archive_edition_identifiers(self):
        self.assertNotEqual(book_identity({"source_url":"https://archive.org/details/edition1"}),book_identity({"source_url":"https://archive.org/details/edition2"}))
    def test_non_github_host_not_a_repo(self):
        self.assertNotEqual(repo_identity({"html_url":"https://example.org/owner/repo"}),repo_identity({"html_url":"https://github.com/owner/repo"}))
