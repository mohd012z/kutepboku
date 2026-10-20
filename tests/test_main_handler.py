"""Regression: main.telegram_handler proxy classes (closure over captured
coroutines — a previous version referenced `original` inside CallbackProxy.answer
and crashed every callback tap with NameError)."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import bot_router
import main
from main import telegram_handler

BOOK = {"id": "b1", "title": "ML Book",
        "source_url": "https://archive.org/download/x/b.pdf", "author": "Unknown"}


class TelegramHandlerProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "TELEGRAM_ALLOWED_USER_IDS": "12345",
            "TELEGRAM_BOT_TOKEN": "123:TEST",
            "MINDA_API_KEY": "",          # intent LLM off -> raw-topic fallback
            "MINDA_BASE_URL": "",
            "BOT_DB_PATH": str(Path(self.temp.name) / "sessions.db"),
        })
        self.env.start()
        bot_router.db = None              # reset module-level store cache

    async def asyncTearDown(self):
        self.env.stop()
        bot_router.db = None
        self.temp.cleanup()

    def _callback_update(self, data, with_message=True):
        """PTB-shaped update for a callback query."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.message = None
        callback = MagicMock()
        callback.data = data
        callback.answer = AsyncMock()
        callback.edit_message_text = AsyncMock()
        if with_message:
            msg = MagicMock()
            msg.reply_text = AsyncMock()
            msg.text = "menu"
            callback.message = msg
        else:
            callback.message = None
        update.callback_query = callback
        update.effective_message = callback.message if with_message else None
        return update

    async def test_category_callback_answers_and_searches(self):
        """The exact crash from the log: ui:cat calls callback.answer() before
        searching. Before the fix this raised NameError: name 'original' is not
        defined. Now the tap is answered and the results are presented."""
        async def provider(query):
            return [dict(BOOK)]
        update = self._callback_update("ui:cat:ml")
        with patch.object(main, "verified_search", provider):
            await telegram_handler(update, MagicMock())
        update.callback_query.answer.assert_awaited()          # no NameError
        update.callback_query.message.reply_text.assert_awaited()  # results shown

    async def test_delivery_link_callback_sends_url(self):
        bot_router.session_store().set_session(
            12345, "CHOOSE_DELIVERY", {"book": dict(BOOK)})
        update = self._callback_update("dl:l")
        await telegram_handler(update, MagicMock())
        update.callback_query.message.reply_text.assert_awaited()
        sent = update.callback_query.message.reply_text.await_args.args[0]
        self.assertIn("https://archive.org/download/x/b.pdf", sent)

    async def test_answer_closure_without_message(self):
        """dl: calls callback.answer('Sending link…') before touching the
        message; with callback.message=None the answer must still be reached
        (proves the closure captures the coroutine, not the 'original' name)."""
        bot_router.session_store().set_session(
            12345, "CHOOSE_DELIVERY", {"book": dict(BOOK)})
        update = self._callback_update("dl:l", with_message=False)
        try:
            await telegram_handler(update, MagicMock())
        except AttributeError:
            pass  # _deliver needs a message to send to; the answer already fired
        update.callback_query.answer.assert_awaited()


if __name__ == "__main__":
    unittest.main()
