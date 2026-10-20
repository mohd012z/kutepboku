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


class SanitizingDelegatingFormatter(logging.Formatter):
    """Preserve a handler's existing formatter and sanitize only its output."""
    def __init__(self, delegate, explicit_tokens=()):
        super().__init__()
        self.delegate = delegate
        self._sanitizer = TelegramSanitizingFormatter(explicit_tokens=explicit_tokens)

    def format(self, record):
        isolated = copy.copy(record)
        isolated.exc_text = None
        rendered = self.delegate.format(isolated)
        for token in self._sanitizer._tokens:
            rendered = rendered.replace(token, "[REDACTED-EXPLICIT]")
        return _TOKEN_PATTERN.sub("bot[REDACTED-PATTERN]", rendered)


def initialize_secure_logging(explicit_tokens=()):
    """Wrap existing Python logging handlers without replacing their configuration.

    Call after logging initialization. Re-run if the application adds handlers later.
    Does not protect direct writes, third-party telemetry or newly attached handlers.
    """
    loggers = [logging.getLogger()]
    loggers.extend(item for item in logging.root.manager.loggerDict.values()
                   if isinstance(item, logging.Logger))
    seen = set()
    for logger in loggers:
        for handler in logger.handlers:
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            current = handler.formatter or logging.Formatter()
            if isinstance(current, SanitizingDelegatingFormatter):
                current = current.delegate
            handler.setFormatter(SanitizingDelegatingFormatter(current, explicit_tokens))
    return len(seen)
