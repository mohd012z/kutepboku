import unittest
from search_identity import normalize_query, book_identity, repo_identity, dedupe_candidates

class SearchIdentityTests(unittest.TestCase):
    def test_normalize_respects_word_boundaries(self):
        self.assertNotEqual(normalize_query("finding aid"), normalize_query("find a book about AI"))
    def test_query_filler(self):
        self.assertEqual(normalize_query("Find me books about Machine Learning"), normalize_query("machine learning"))
    def test_unknown_author_editions_remain_distinct(self):
        a={"title":"Python Guide","source_url":"https://example.org/a"}
        b={"title":"Python Guide","source_url":"https://example.org/b"}
        self.assertNotEqual(book_identity(a),book_identity(b))
    def test_known_title_author(self):
        a={"title":"Python Guide","author":"A Writer","source_url":"https://example.org/a"}
        b={"title":"PYTHON GUIDE","author":"A Writer","source_url":"https://example.org/b"}
        self.assertEqual(book_identity(a),book_identity(b))
    def test_archive_identifier(self):
        a={"title":"A","source_url":"https://archive.org/details/abc123"}
        b={"title":"B","source_url":"https://archive.org/download/abc123/book.pdf"}
        self.assertEqual(book_identity(a),book_identity(b))
    def test_repo_case(self):
        self.assertEqual(repo_identity({"full_name":"Owner/Repo"}),repo_identity({"html_url":"https://github.com/owner/repo"}))
    def test_dedup_preserves_first_and_provenance(self):
        x=dedupe_candidates([{"full_name":"Owner/Repo","source":"curated"},{"full_name":"owner/repo","source":"github"}],repo_identity)
        self.assertEqual(len(x),1)
        self.assertEqual(x[0]["full_name"],"Owner/Repo")
        self.assertEqual(len(x[0]["provenance"]),2)

if __name__=="__main__": unittest.main()
