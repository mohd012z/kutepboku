"""Offline credential-redaction tests; never contact Telegram."""
import io
import logging
import unittest
from unittest.mock import patch

import requests

from logging_config import TelegramSanitizingFormatter, inventory_logging_handlers
from telegram_vault import TelegramVaultClient


class LoggingAuditTests(unittest.TestCase):
    TOKEN = "999888:FAKE-TEST-TOKEN-XYZ987654321"

    def test_interpolation_and_traceback_are_sanitized_without_record_mutation(self):
        formatter = TelegramSanitizingFormatter(
            "%(levelname)s %(message)s", explicit_tokens=[self.TOKEN])
        url = "https://api.telegram.org/bot" + self.TOKEN + "/getFile"
        logger = logging.getLogger("vault.logging.audit")
        record = logger.makeRecord(logger.name, logging.ERROR, __file__, 1,
                                   "Request to %s", (url,), None)
        original_msg, original_args = record.msg, record.args
        result = formatter.format(record)
        self.assertNotIn(self.TOKEN, result)
        self.assertIn("[REDACTED-EXPLICIT]", result)
        self.assertEqual(record.msg, original_msg)
        self.assertEqual(record.args, original_args)
        self.assertIsNone(record.exc_text)

        try:
            raise requests.exceptions.RequestException("Failed " + url)
        except requests.exceptions.RequestException:
            import sys
            info = sys.exc_info()
        record = logger.makeRecord(logger.name, logging.ERROR, __file__, 2,
                                   "Failure", (), info)
        result = formatter.format(record)
        self.assertNotIn(self.TOKEN, result)
        self.assertIn("[REDACTED-EXPLICIT]", result)
        self.assertIsNone(record.exc_text)

    def test_pattern_fallback_and_multiple_handler_isolation(self):
        logger = logging.getLogger("vault.logging.audit.multiple")
        previous_level, previous_propagate = logger.level, logger.propagate
        original_handlers = list(logger.handlers)
        streams = [io.StringIO(), io.StringIO()]
        handlers = [logging.StreamHandler(stream) for stream in streams]
        for handler in handlers:
            handler.setFormatter(TelegramSanitizingFormatter("%(message)s"))
        try:
            logger.handlers = handlers
            logger.propagate = False
            logger.setLevel(logging.DEBUG)
            logger.error("https://api.telegram.org/bot123456:synthetic_TOKEN/sendDocument")
            for stream in streams:
                self.assertNotIn("123456:synthetic_TOKEN", stream.getvalue())
                self.assertIn("bot[REDACTED-PATTERN]", stream.getvalue())
        finally:
            logger.handlers = original_handlers
            logger.propagate = previous_propagate
            logger.setLevel(previous_level)
            for handler in handlers:
                handler.close()
            for stream in streams:
                stream.close()

    def test_request_url_preserved_and_no_network_called(self):
        token = self.TOKEN
        with patch("telegram_vault.requests.post") as post:
            response = post.return_value
            response.json.return_value = {"ok": True, "result": True}
            client = TelegramVaultClient(bot_token=token, channel_id="-10099")
            self.assertTrue(client._api("pinChatMessage"))
            sent_url = post.call_args.args[0]
            self.assertIn(token, sent_url)
            self.assertEqual(sent_url, client.base_url + "/pinChatMessage")


    def test_binding_preserves_format_and_restores_original_handler(self):
        from logging_config import initialize_secure_logging, SanitizingDelegatingFormatter
        logger = logging.getLogger("vault.logging.audit.binding")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        original = logging.Formatter("ORIGINAL:%(levelname)s:%(message)s")
        handler.setFormatter(original)
        logger.addHandler(handler)
        old_level, old_propagate = logger.level, logger.propagate
        try:
            logger.setLevel(logging.ERROR)
            logger.propagate = False
            initialize_secure_logging(explicit_tokens=[self.TOKEN])
            self.assertIsInstance(handler.formatter, SanitizingDelegatingFormatter)
            logger.error("URL https://api.telegram.org/bot%s/getFile", self.TOKEN)
            self.assertIn("ORIGINAL:ERROR:", stream.getvalue())
            self.assertNotIn(self.TOKEN, stream.getvalue())
            self.assertIn("[REDACTED-EXPLICIT]", stream.getvalue())
        finally:
            logger.removeHandler(handler)
            handler.setFormatter(original)
            logger.setLevel(old_level)
            logger.propagate = old_propagate
            handler.close()
            stream.close()

    def test_inventory_identifies_registered_handler(self):
        logger = logging.getLogger("vault.logging.audit.inventory")
        handler = logging.StreamHandler(io.StringIO())
        handler.setFormatter(TelegramSanitizingFormatter())
        logger.addHandler(handler)
        try:
            inventory = inventory_logging_handlers()
            self.assertTrue(any(item["logger"] == logger.name and
                                item["formatter"] == "TelegramSanitizingFormatter"
                                for item in inventory))
        finally:
            logger.removeHandler(handler)
            handler.close()
