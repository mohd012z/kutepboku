"""Output-only Telegram credential redaction for application-controlled logging handlers.

Attach this formatter to each actual sink. It does not intercept third-party
telemetry, direct writes, or handlers using other formatters.
"""
import copy
import logging
import re

_TOKEN_PATTERN = re.compile(r"bot[0-9]+:[A-Za-z0-9_-]+")


class TelegramSanitizingFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, *, explicit_tokens=()):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._tokens = tuple(sorted((str(token) for token in explicit_tokens if token),
                                    key=len, reverse=True))

    def format(self, record):
        # Formatter.format caches exc_text; isolate it from other handlers.
        isolated = copy.copy(record)
        isolated.exc_text = None
        rendered = super().format(isolated)
        for token in self._tokens:
            rendered = rendered.replace(token, "[REDACTED-EXPLICIT]")
        return _TOKEN_PATTERN.sub("bot[REDACTED-PATTERN]", rendered)


def inventory_logging_handlers():
    """Return active logger/handler metadata without disclosing log payloads."""
    loggers = [logging.getLogger()]
    loggers.extend(item for item in logging.root.manager.loggerDict.values()
                   if isinstance(item, logging.Logger))
    return [
        {"logger": logger.name or "root", "handler": type(handler).__name__,
         "formatter": type(handler.formatter).__name__ if handler.formatter else None,
         "level": logging.getLevelName(handler.level)}
        for logger in loggers for handler in logger.handlers
    ]
