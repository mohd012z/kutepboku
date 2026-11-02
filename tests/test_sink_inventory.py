"""Offline sink lifecycle audit. Synthetic credentials only; no HTTP requests."""
import io
import logging
import unittest
from unittest.mock import patch

from logging_config import (
    SanitizingDelegatingFormatter,
    TelegramSanitizingFormatter,
    initialize_secure_logging,
    inventory_logging_handlers,
)


def is_sanitized(handler):
    return isinstance(handler.formatter, (SanitizingDelegatingFormatter, TelegramSanitizingFormatter))


class SinkInventoryTests(unittest.TestCase):
    TOKEN = "123456789:FAKE_AUDIT_TOKEN_abc"

    def test_existing_root_and_named_handlers_are_wrapped(self):
        root = logging.getLogger()
        named = logging.getLogger("kutepboku.audit.synthetic")
        streams = [io.StringIO(), io.StringIO()]
        handlers = [logging.StreamHandler(stream) for stream in streams]
        original = [handler.formatter for handler in handlers]
        old_propagate, old_level = named.propagate, named.level
        try:
            named.propagate = False
            named.setLevel(logging.ERROR)
            root.addHandler(handlers[0])
            named.addHandler(handlers[1])
            initialize_secure_logging(explicit_tokens=[self.TOKEN])
            self.assertTrue(all(is_sanitized(handler) for handler in handlers))
            named.error("https://api.telegram.org/bot%s/getFile", self.TOKEN)
            self.assertNotIn(self.TOKEN, streams[1].getvalue())
            inventory = inventory_logging_handlers()
            self.assertTrue(any(item["logger"] == named.name for item in inventory))
        finally:
            root.removeHandler(handlers[0])
            named.removeHandler(handlers[1])
            for handler, fmt, stream in zip(handlers, original, streams):
                handler.setFormatter(fmt)
                handler.close()
                stream.close()
            named.propagate, named.level = old_propagate, old_level

    def test_late_handler_requires_rebinding(self):
        logger = logging.getLogger("kutepboku.audit.late")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        original = handler.formatter
        old_propagate, old_level = logger.propagate, logger.level
        try:
            logger.propagate = False
            logger.setLevel(logging.ERROR)
            initialize_secure_logging(explicit_tokens=[self.TOKEN])
            logger.addHandler(handler)
            self.assertFalse(is_sanitized(handler), "New handlers are not automatically protected")
            initialize_secure_logging(explicit_tokens=[self.TOKEN])
            self.assertTrue(is_sanitized(handler))
            logger.error("request https://api.telegram.org/bot%s/sendDocument", self.TOKEN)
            self.assertNotIn(self.TOKEN, stream.getvalue())
        finally:
            logger.removeHandler(handler)
            handler.setFormatter(original)
            logger.propagate, logger.level = old_propagate, old_level
            handler.close()
            stream.close()

    def test_application_rotating_file_sink_is_sanitized_after_binding(self):
        # Test the real logger factory with a temporary log directory, no Telegram access.
        import tempfile
        from logger_config import setup_logger
        logger = logging.getLogger("kutepboku")
        original_handlers = list(logger.handlers)
        old_level, old_propagate = logger.level, logger.propagate
        try:
            for handler in original_handlers:
                logger.removeHandler(handler)
            with tempfile.TemporaryDirectory() as directory:
                with patch.dict("os.environ", {"BOT_LOG_DIR": directory}):
                    setup_logger()
                self.assertTrue(any(type(h).__name__ == "RotatingFileHandler" for h in logger.handlers))
                initialize_secure_logging(explicit_tokens=[self.TOKEN])
                self.assertTrue(all(is_sanitized(h) for h in logger.handlers))
                logger.error("https://api.telegram.org/bot%s/getFile", self.TOKEN)
                from pathlib import Path
                contents = (Path(directory) / "bot_errors.log").read_text(encoding="utf-8")
                self.assertNotIn(self.TOKEN, contents)
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()
        finally:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            for handler in original_handlers:
                logger.addHandler(handler)
            logger.level, logger.propagate = old_level, old_propagate


if __name__ == "__main__":
    unittest.main()
