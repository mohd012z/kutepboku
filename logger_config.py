"""Minimal privacy-conscious logging for bot delivery operations."""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger(log_dir=None):
    logger = logging.getLogger("kutepboku")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)
    directory = log_dir if log_dir is not None else os.getenv("BOT_LOG_DIR")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path / "bot_errors.log", maxBytes=2_000_000,
                                           backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.ERROR)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    return logger


logger = setup_logger()
