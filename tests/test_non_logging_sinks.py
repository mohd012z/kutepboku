"""Offline checks for non-logging credential output paths.

These tests document limitations rather than claiming arbitrary stdout/stderr
or third-party debug streams are automatically sanitized.
"""
import ast
import contextlib
import http.client
import io
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "999999:FAKE_NONLOGGING_AUDIT_TOKEN"
# The log rotation CLI reports aggregate counts only, not credentials.
ALLOWED_PRINTS = {"log_rotator.py"}
# Other direct-output call sites require separate review; do not silently
# classify them as safe based on this focused vault test.
CRITICAL_RUNTIME_MODULES = {"main.py", "telegram_vault.py", "cloud_backup.py", "logging_config.py"}


class NonLoggingSinkTests(unittest.TestCase):
    def test_http_debugging_is_off_by_default(self):
        self.assertEqual(http.client.HTTPConnection.debuglevel, 0)
        self.assertEqual(http.client.HTTPSConnection.debuglevel, 0)

    def test_http_debug_can_bypass_logging_formatters(self):
        # No socket connection or HTTP request is made. This deliberately
        # demonstrates why sanitizing Python loggers is insufficient.
        connection = http.client.HTTPConnection("example.invalid")
        output = io.StringIO()
        try:
            connection.set_debuglevel(1)
            with contextlib.redirect_stdout(output):
                connection.sock = type("FakeSocket", (), {"sendall": lambda self, data: None})()
                connection.send(b"GET /bot" + TOKEN.encode() + b"/getMe HTTP/1.1\\r\\n\\r\\n")
            self.assertIn(TOKEN, output.getvalue(),
                          "Expected to demonstrate raw HTTP debug output")
        finally:
            connection.close()
        # Never emit captured synthetic credentials into CI logs.

    def test_production_source_does_not_enable_http_debug(self):
        excluded = {"tests", ".git", ".venv", "venv"}
        violations = []
        for path in ROOT.rglob("*.py"):
            if any(part in excluded for part in path.relative_to(ROOT).parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "set_debuglevel" and (
                        not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != 0
                    ):
                        violations.append(f"{path.name}:{node.lineno} set_debuglevel")
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and target.attr == "debuglevel" and (
                            not isinstance(node.value, ast.Constant) or node.value.value != 0
                        ):
                            violations.append(f"{path.name}:{node.lineno} debuglevel assignment")
        self.assertEqual(violations, [], "Production code enables HTTP debugging")

    def test_print_calls_are_reviewed(self):
        unexpected = []
        for path in ROOT.glob("*.py"):
            if path.name not in CRITICAL_RUNTIME_MODULES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    if path.name not in ALLOWED_PRINTS:
                        unexpected.append(f"{path.name}:{node.lineno}")
        self.assertEqual(unexpected, [], "Review raw print() sinks before deployment")

    def test_redirected_streams_are_not_claimed_to_be_sanitized(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            print("kutepboku operational")
        self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
