"""Offline integration checks for live runner routing and admin boundaries."""
import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from main import manual_backup_command, status_command, telegram_handler


def fake_update(user_id=100, chat_type="private", text="/status"):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(type=chat_type),
        message=message,
        effective_message=message,
        callback_query=None,
    )


class AdminCommandTests(unittest.TestCase):
    def test_missing_admin_id_denies_backup_and_status(self):
        with patch.dict(os.environ, {"ADMIN_CHAT_ID": ""}):
            for command in (manual_backup_command, status_command):
                update = fake_update()
                with patch("main.backup_database_snapshot") as backup, patch("main.status_snapshot") as status:
                    asyncio.run(command(update, None))
                    update.message.reply_text.assert_awaited_once_with("Not authorized.")
                    backup.assert_not_called()
                    status.assert_not_called()

    def test_non_admin_denied(self):
        with patch.dict(os.environ, {"ADMIN_CHAT_ID": "200"}):
            update = fake_update(user_id=100)
            asyncio.run(status_command(update, None))
            update.message.reply_text.assert_awaited_once_with("Not authorized.")

    def test_admin_status_diagnostics(self):
        with patch.dict(os.environ, {"ADMIN_CHAT_ID": "100"}):
            update = fake_update()
            with patch("main.status_snapshot", return_value={
                "exists": False, "size_bytes": None, "integrity": "missing",
                "stored_sessions": None, "active_24h": None, "uptime_seconds": 61,
            }):
                asyncio.run(status_command(update, None))
            report = update.message.reply_text.await_args.args[0]
            self.assertIn("SQLite integrity: missing", report)
            self.assertIn("Uptime: 0h 1m", report)

    def test_group_chat_cannot_invoke_backup(self):
        with patch.dict(os.environ, {"ADMIN_CHAT_ID": "100"}):
            update = fake_update(chat_type="group")
            with patch("main.backup_database_snapshot") as backup:
                asyncio.run(manual_backup_command(update, None))
                backup.assert_not_called()

    def test_message_routes_to_fsm(self):
        update = fake_update(text="/start")
        with patch("main.handle_update", new_callable=AsyncMock) as router:
            asyncio.run(telegram_handler(update, None))
            router.assert_awaited_once()
            self.assertEqual(router.await_args.kwargs["search_provider"].__name__, "verified_search")
