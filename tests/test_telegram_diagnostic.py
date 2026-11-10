"""Offline regressions for redacted, read-only Telegram webhook diagnostics."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "cloudflare" / "diagnose_telegram.py"
SPEC = importlib.util.spec_from_file_location("msasoup_telegram_diagnostic", SCRIPT)
DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTIC)


class TelegramDiagnosticTests(unittest.TestCase):
    TOKEN = "12345:do-not-print-this-token"

    def run_diagnostic(self, responses, token=TOKEN):
        output = io.StringIO()
        environment = {"TELEGRAM_BOT_TOKEN": token} if token else {}
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(DIAGNOSTIC, "call", side_effect=responses) as api:
                with contextlib.redirect_stdout(output):
                    exit_code = DIAGNOSTIC.main()
        return exit_code, output.getvalue(), api

    def test_expected_webhook_does_not_print_url_or_telegram_error(self):
        error_canary = "PRIVATE-TELEGRAM-ERROR-DETAIL"
        responses = [
            {"username": "mysoupsearchbot"},
            {
                "url": DIAGNOSTIC.EXPECTED_WEBHOOK,
                "pending_update_count": 3,
                "last_error_message": error_canary,
                "allowed_updates": ["message", "callback_query"],
            },
        ]
        code, output, api = self.run_diagnostic(responses)
        self.assertEqual(code, 0)
        self.assertIn("Webhook ownership: PASS", output)
        self.assertIn("Webhook destination: EXPECTED", output)
        self.assertIn("Last delivery error present: True", output)
        self.assertIn("a real /menu reply is still required", output)
        self.assertNotIn(DIAGNOSTIC.EXPECTED_WEBHOOK, output)
        self.assertNotIn(error_canary, output)
        self.assertNotIn(self.TOKEN, output)
        self.assertEqual([call.args[0] for call in api.call_args_list], ["getMe", "getWebhookInfo"])

    def test_unexpected_webhook_is_redacted_and_never_registered(self):
        foreign_url = "https://foreign.example/telegram?secret=WEBHOOK-CANARY"
        code, output, api = self.run_diagnostic([
            {"username": "mysoupsearchbot"},
            {"url": foreign_url, "last_error_message": "ERROR-CANARY"},
        ])
        self.assertEqual(code, 1)
        self.assertIn("Webhook ownership: FAIL", output)
        self.assertIn("Webhook destination: DIFFERENT (redacted)", output)
        self.assertIn("STOP: inspect existing polling/webhook owner", output)
        self.assertNotIn(foreign_url, output)
        self.assertNotIn("ERROR-CANARY", output)
        self.assertNotIn(self.TOKEN, output)
        self.assertEqual(api.call_count, 2)

    def test_missing_token_fails_closed_without_api_access(self):
        code, output, api = self.run_diagnostic([], token="")
        self.assertEqual(code, 2)
        self.assertIn("UNVERIFIED: TELEGRAM_BOT_TOKEN secret is absent", output)
        api.assert_not_called()

    def test_wrong_identity_stops_before_webhook_inspection(self):
        code, output, api = self.run_diagnostic([{"username": "other_bot"}])
        self.assertEqual(code, 1)
        self.assertIn("Identity: FAIL", output)
        self.assertIn("STOP: bot identity does not match", output)
        self.assertNotIn(self.TOKEN, output)
        self.assertEqual(api.call_count, 1)

    def test_webhook_lookup_failure_is_unverified_not_success(self):
        code, output, api = self.run_diagnostic([{"username": "mysoupsearchbot"}, None])
        self.assertEqual(code, 2)
        self.assertIn("UNVERIFIED: getWebhookInfo request failed", output)
        self.assertNotIn("Routing metadata PASS", output)
        self.assertEqual(api.call_count, 2)


if __name__ == "__main__":
    unittest.main()
