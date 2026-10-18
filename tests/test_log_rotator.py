import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from log_rotator import archive_rotated_logs


class LogRotatorTests(unittest.TestCase):
    def test_missing_directory(self):
        with TemporaryDirectory() as root:
            self.assertEqual(archive_rotated_logs(Path(root) / "missing")["archived"], 0)

    def test_active_log_not_modified(self):
        with TemporaryDirectory() as root:
            active = Path(root) / "bot_errors.log"
            active.write_text("active log")
            result = archive_rotated_logs(root)
            self.assertEqual(result["archived"], 0)
            self.assertEqual(active.read_text(), "active log")

    def test_archive_rotated_backup(self):
        with TemporaryDirectory() as root:
            active = Path(root) / "bot_errors.log"
            active.write_text("active")
            rotated = Path(root) / "bot_errors.log.1"
            rotated.write_text("old errors")
            result = archive_rotated_logs(root)
            self.assertEqual(result["archived"], 1)
            self.assertFalse(rotated.exists())
            self.assertEqual(active.read_text(), "active")
            archives = list((Path(root) / "archives").glob("*.zip"))
            self.assertEqual(len(archives), 1)
            with zipfile.ZipFile(archives[0]) as z:
                self.assertEqual(z.read("bot_errors.log.1"), b"old errors")

    def test_unrelated_files_untouched(self):
        with TemporaryDirectory() as root:
            unrelated = Path(root) / "bot_errors.log.custom"
            unrelated.write_text("keep")
            archive_rotated_logs(root)
            self.assertTrue(unrelated.exists())

    def test_retention_limit(self):
        with TemporaryDirectory() as root:
            for n in range(3):
                (Path(root) / f"bot_errors.log.{n + 1}").write_text(str(n))
            result = archive_rotated_logs(root, max_archives=2)
            self.assertEqual(result["archived"], 3)
            self.assertEqual(len(list((Path(root) / "archives").glob("*.zip"))), 2)

    def test_invalid_retention(self):
        with TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                archive_rotated_logs(root, max_archives=0)


if __name__ == "__main__":
    unittest.main()
