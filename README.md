# msasoup

[![msasoup CI](https://github.com/mohd012z/kutepboku/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mohd012z/kutepboku/actions/workflows/ci.yml)

Autonomous open-license eBook scout delivering to Telegram [@mysoupsearchbot](https://t.me/mysoupsearchbot).

## Setup

1. Create the Telegram bot with BotFather, start a chat with it, and obtain your chat ID.
2. Set GitHub Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Optionally set repository variable `SCOUT_QUERY` (default: `python programming`).
4. Enable GitHub Actions and allow workflow write permission to persist delivery history.
5. Run **msasoup daily delivery** manually; daily schedule is 00:00 UTC / 08:00 Malaysia time.

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

The interactive router, delivery gateways and encrypted local restore utilities require live integration testing before production use. Automatic Telegram vault backup/recovery and Google/Gemini search are not currently verified or deployed. The optional runner backup hook is disabled by default and is not a persistent-host backup solution.

## Limitations

GitHub Actions runs only after the workflow reaches the default branch. Scheduled execution may be delayed. getMe does not confirm chat delivery permissions. Real Telegram delivery requires credentials and a live test. External catalog metadata is not a substitute for independent rights review.
