"""Archive completed RotatingFileHandler backups, never the active log.

Run on the persistent host with the logger's directory. The logger itself
rotates active files; this utility only compresses closed backup files.
"""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import os
import zipfile

from logger_config import logger


def archive_rotated_logs(log_dir=None, *, max_archives=30):
    directory = Path(log_dir or os.getenv("BOT_LOG_DIR") or "logs")
    archive_dir = directory / "archives"
    if not directory.is_dir():
        return {"archived": 0, "errors": 0, "status": "no_log_directory"}
    if not isinstance(max_archives, int) or max_archives < 1:
        raise ValueError("max_archives must be positive")
    archived = 0
    errors = 0
    for source in sorted(directory.glob("bot_errors.log.*")):
        if not source.is_file() or source.is_symlink():
            continue
        # Only numbered files created by RotatingFileHandler are eligible.
        if not source.name.removeprefix("bot_errors.log.").isdigit():
            continue
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = archive_dir / ("bot_errors_" + stamp + "_" + uuid4().hex[:8] + ".zip")
        temporary = archive_dir / (destination.name + ".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(source, arcname=source.name)
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise OSError("Archive verification failed")
            os.replace(temporary, destination)
            source.unlink()
            archived += 1
        except (OSError, zipfile.BadZipFile, RuntimeError):
            errors += 1
            logger.error("log_archive_failed file=%s", source.name)
            temporary.unlink(missing_ok=True)
    if archive_dir.is_dir():
        archives = sorted(archive_dir.glob("bot_errors_*.zip"),
                          key=lambda path: path.stat().st_mtime, reverse=True)
        for old in archives[max_archives:]:
            try:
                old.unlink()
            except OSError:
                errors += 1
                logger.error("log_archive_retention_failed")
    return {"archived": archived, "errors": errors, "status": "ok" if not errors else "partial_failure"}


if __name__ == "__main__":
    print(archive_rotated_logs())
