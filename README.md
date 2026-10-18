# msasoup

[![msasoup CI](https://github.com/mohd012z/kutepboku/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mohd012z/kutepboku/actions/workflows/ci.yml)

Autonomous open-license eBook scout delivering to Telegram [@mysoupsearchbot](https://t.me/mysoupsearchbot).

## Setup

1. Create the Telegram bot with BotFather, start a chat with it, and obtain your chat ID.
2. Set GitHub Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Optionally set repository variable `SCOUT_QUERY` (default: `python programming`).
4. Enable GitHub Actions and allow workflow write permission to persist delivery history.
5. Run **Ebook Scout Agent & Maintenance** manually, optionally entering a custom `search_query`. The scheduled scout runs every four hours at 00:00, 04:00, 08:00, 12:00, 16:00 and 20:00 UTC (08:00, 12:00, 16:00, 20:00, 00:00 and 04:00 Malaysia time). GitHub Actions schedules can be delayed.

## Tests

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The CI workflow runs the test suite under Coverage.py and uploads `coverage-xml` and `code-coverage-report` artifacts (14-day retention). Download `code-coverage-report` from a workflow run, extract it, and open `index.html` to inspect covered and missing lines. The CI badge above reflects the default branch; it does not verify live bot deployment.

Codecov upload and its percentage badge are **not yet configured**. The local XML artifact does not automatically publish results to Codecov.

The agent verifies the bot identity via Telegram getMe before searching. It discovers public scans through Open Library, checks Internet Archive licensing metadata, validates document bytes, hashes downloads for deduplication and sends authorized documents. Missing or unsupported licenses are rejected.

## Architecture and release readiness

The current scheduled entry point is `agent.py` at the repository root. Supporting modules also remain at the root until their imports and execution paths can be migrated safely. Tests are under `tests/`. See [CONTRIBUTING.md](CONTRIBUTING.md) for development instructions.

The interactive router, delivery gateways and encrypted local restore utilities require live integration testing before production use. A manual, admin-restricted encrypted Telegram vault backup is implemented but not live-tested; automatic recovery is not implemented. Google/Gemini search is implemented as a fail-closed adapter but is not live-tested or deployed. The scheduled runner does not restore or back up the persistent polling database; backup and recovery must run on the host that owns that database.

## Manual encrypted backup

The optional live polling runner (`python main.py`) supports `/backup` in a private chat, restricted to the Telegram **user ID** configured in `ADMIN_CHAT_ID`. Set `TELEGRAM_BACKUP_CHANNEL_ID` to a private channel where the bot has permission to post documents and pin messages. Generate a Fernet key and set `BACKUP_ENCRYPTION_KEY`; retain it securely outside the bot or recovery will be impossible. `BOT_DB_PATH` selects the running bot's SQLite database. The command creates a consistent SQLite snapshot, encrypts it, uploads it, then requests pinning. It never sends the unencrypted database to Telegram. Backup is **not** automatic restore and is not verified live.

## Admin diagnostics

Send `/status` in a private chat with the polling bot as the user identified by `ADMIN_CHAT_ID`. The command reports process uptime, SQLite database presence and size, read-only integrity status, total stored sessions and sessions updated in the last 24 hours. It does not expose user identifiers, does not create a missing database, and does not prove that scheduled GitHub Actions or external search providers are healthy.

## Limitations

GitHub Actions runs only after the workflow reaches the default branch. Scheduled execution may be delayed. getMe does not confirm chat delivery permissions. Real Telegram delivery requires credentials and a live test. External catalog metadata is not a substitute for independent rights review.
