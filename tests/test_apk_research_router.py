"""Offline router integration tests; no Telegram requests or database writes."""
import asyncio
import os
import unittest
from unittest.mock import patch
from bot_router import handle_update

class Store:
    def __init__(self):
        self.state = ("WAITING_FOR_QUERY", {})
        self.writes = []
    def set_session(self, *args):
        self.writes.append(args)
    def get_session(self, user_id):
        return self.state
    def clear_session(self, user_id):
        self.writes.append(("clear", user_id))

class Message:
    def __init__(self, text):
        self.text = text
        self.replies = []
    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))

class Callback:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []
    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))
    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))

class Update:
    def __init__(self, text=None, callback=None, user_id=10):
        self.effective_user = type("User", (), {"id": user_id})()
        self.message = Message(text) if text is not None else None
        self.callback_query = Callback(callback) if callback is not None else None

class RouterIntegrationTests(unittest.TestCase):
    def run_update(self, update, flag):
        store = Store()
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USER_IDS": "10", "MSASOUP_APK_RESEARCH_STAGING": flag}):
            asyncio.run(handle_update(update, None, store=store))
        return store
    def test_disabled_command(self):
        u = Update("/apk_research")
        self.run_update(u, "0")
        self.assertEqual(u.message.replies[0][0], "Research menu disabled.")
    def test_enabled_command(self):
        u = Update("/apk_research")
        self.run_update(u, "1")
        self.assertEqual(len(u.message.replies[0][1]["reply_markup"]["inline_keyboard"]), 6)
    def test_disabled_callback(self):
        u = Update(callback="apk:v1:tools")
        self.run_update(u, "0")
        self.assertEqual(len(u.callback_query.edits), 0)
    def test_enabled_callback(self):
        u = Update(callback="apk:v1:ads")
        self.run_update(u, "1")
        self.assertIn("Ad SDK Research", u.callback_query.edits[0][0])
    def test_unknown_callback(self):
        u = Update(callback="apk:v1:unknown")
        self.run_update(u, "1")
        self.assertEqual(u.callback_query.edits, [])
    def test_unauthorized(self):
        u = Update("/apk_research", user_id=11)
        self.run_update(u, "1")
        self.assertEqual(u.message.replies, [])
    def test_start_unchanged(self):
        u = Update("/start")
        store = self.run_update(u, "1")
        self.assertEqual(store.writes[0][1], "WAITING_FOR_QUERY")
        self.assertIn("eBook", u.message.replies[0][0])
    def test_research_no_session_mutation(self):
        u = Update("/apk_research")
        store = self.run_update(u, "1")
        self.assertEqual(store.writes, [])
    def test_callback_no_session_mutation(self):
        u = Update(callback="apk:v1:security")
        store = self.run_update(u, "1")
        self.assertEqual(store.writes, [])

if __name__ == "__main__":
    unittest.main()
