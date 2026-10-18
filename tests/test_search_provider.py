import unittest
from unittest.mock import Mock

from search_provider import archive_rights_checker


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
        self.assertFalse(archive_rights_checker(
            "https://archive.org/download/bookid/book.pdf", {}, session=session
        ))
