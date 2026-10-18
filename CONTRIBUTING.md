# Contributing to kutepboku

## Development

Use Python 3.11. Install dependencies with `python -m pip install -r requirements.txt` and run `python -m unittest discover -s tests -v`. To measure coverage locally, run `coverage run --source=. --omit='*/tests/*,*/test_*.py' -m unittest discover -s tests -v` followed by `coverage report -m`.

## Pull requests

Branch from `main`, make narrowly scoped changes, and add tests for new behavior. Check the **msasoup CI** workflow before requesting merge. Never commit tokens, personal information, runtime SQLite databases, or logs. Do not disable integrity checks to satisfy tests.

## Architecture and release status

The scheduled scout runs `python agent.py` from the repository root. Root-level Python modules are currently used by other modules and tests. Do not move them into `src/` without updating every import, entry point, test and workflow together. The interactive Telegram router and delivery modules are scaffolding, not proof of a deployed live bot.

Telegram backup synchronization, automatic cloud restore, Google/Gemini search, and Codecov publication are not verified production features. Describe them as planned until implemented and integration-tested.
