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


    def test_run_uses_manual_override_without_network(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import os
        with TemporaryDirectory() as folder:
            history = Path(folder) / "history.json"
            with patch.dict(os.environ, {
                "CUSTOM_QUERY": "Embedded Rust Architecture",
                "SCOUT_QUERY": "python programming",
                "TELEGRAM_BOT_TOKEN": "123:abc",
                "TELEGRAM_CHAT_ID": "12345",
            }), patch.object(agent, "verify_bot", return_value={
                "username": "mysoupsearchbot", "id": 7,
            }), patch.object(agent, "discover", return_value=[]) as discover, patch.object(
                agent, "send"
            ) as send, patch.object(agent, "Path", side_effect=lambda value: history if value == "state/history.json" else Path(value)):
                agent.run()
                discover.assert_called_once()
                self.assertEqual(discover.call_args.args[1], "Embedded Rust Architecture")
                send.assert_not_called()

    def test_run_uses_scheduled_query_without_network(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import os
        with TemporaryDirectory() as folder:
            history = Path(folder) / "history.json"
            with patch.dict(os.environ, {
                "SCOUT_QUERY": "Systems Architecture",
                "TELEGRAM_BOT_TOKEN": "123:abc",
                "TELEGRAM_CHAT_ID": "12345",
            }, clear=True), patch.object(agent, "verify_bot", return_value={
                "username": "mysoupsearchbot", "id": 7,
            }), patch.object(agent, "discover", return_value=[]) as discover, patch.object(
                agent, "send"
            ) as send, patch.object(agent, "Path", side_effect=lambda value: history if value == "state/history.json" else Path(value)):
                agent.run()
                self.assertEqual(discover.call_args.args[1], "Systems Architecture")
                send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
