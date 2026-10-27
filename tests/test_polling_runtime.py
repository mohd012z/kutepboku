import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import main
from telegram.error import Conflict, Forbidden, NetworkError
from runtime_guard import polling_lock


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_webhook_is_preserved(self):
        bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(
            is_bot=True, username=main.BOT_NAME)),
            get_webhook_info=AsyncMock(return_value=SimpleNamespace(url='https://existing.example')))
        with self.assertRaisesRegex(RuntimeError, 'webhook'):
            await main.verify_identity(SimpleNamespace(bot=bot))

    async def test_polling_conflict_stops_application(self):
        app = SimpleNamespace(bot_data={}, stop_running=MagicMock())
        await main.polling_error(None, SimpleNamespace(error=Conflict('sensitive URL'), application=app))
        app.stop_running.assert_called_once()
        self.assertEqual(app.bot_data['runtime_exit_code'], 78)

    async def test_transient_network_error_keeps_poller_running(self):
        app = SimpleNamespace(bot_data={}, stop_running=MagicMock())
        await main.polling_error(None, SimpleNamespace(error=NetworkError('sensitive URL'), application=app))
        app.stop_running.assert_not_called()

    async def test_one_blocked_recipient_does_not_stop_other_users(self):
        app = SimpleNamespace(bot_data={}, stop_running=MagicMock())
        await main.polling_error(object(), SimpleNamespace(error=Forbidden('blocked'), application=app))
        app.stop_running.assert_not_called()


class ConfigurationTests(unittest.TestCase):
    def test_duplicate_listener_lock_is_released_after_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'poller.lock'
            with self.assertRaisesRegex(ValueError, 'simulated crash'):
                with polling_lock(path):
                    with self.assertRaises(RuntimeError):
                        with polling_lock(path):
                            self.fail('second consumer started')
                    raise ValueError('simulated crash')
            with polling_lock(path):
                pass

    def test_one_status_handler_and_error_handler(self):
        with patch.dict('os.environ', {}, clear=True):
            application = main.build_application('12345:offline-test-token')
        status_handlers = [handler for group in application.handlers.values()
                           for handler in group if 'status' in getattr(handler, 'commands', [])]
        self.assertEqual(len(status_handlers), 1)
        self.assertIn(main.polling_error, application.error_handlers)


if __name__ == '__main__':
    unittest.main()
