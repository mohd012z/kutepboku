import unittest
from unittest.mock import Mock, patch
import agent


class AgentTests(unittest.TestCase):
    def test_invalid_token(self):
        with self.assertRaises(ValueError):
            agent.verify_bot(Mock(), "")

    def test_wrong_identity(self):
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            "ok": True, "result": {"is_bot": True, "username": "wrong"}}
        with self.assertRaises(RuntimeError):
            agent.verify_bot(session, "123:abc")

    def test_verified_identity(self):
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            "ok": True, "result": {"is_bot": True, "username": "mysoupsearchbot", "id": 7}}
        self.assertEqual(agent.verify_bot(session, "123:abc")["id"], 7)

    def test_license_rejection(self):
        self.assertFalse(agent.licensed({"metadata": {"licenseurl": "https://example.com"}}))

    def test_license_acceptance(self):
        self.assertTrue(agent.licensed({"metadata": {
            "licenseurl": "https://creativecommons.org/licenses/by/4.0/"}}))

    def test_private_url(self):
        self.assertFalse(agent.safe_url("http://127.0.0.1/book.pdf"))
        self.assertFalse(agent.safe_url("https://user:pass@example.com/book.pdf"))

    def test_bad_document(self):
        response = Mock()
        response.iter_content.return_value = iter([b"not a pdf" * 300])
        with patch.object(agent, "get", return_value=response):
            with self.assertRaises(ValueError):
                agent.download(Mock(), "https://example.com/book.pdf")


if __name__ == "__main__":
    unittest.main()
