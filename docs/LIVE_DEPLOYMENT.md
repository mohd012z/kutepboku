# Live polling deployment and verification

The GitHub Actions scheduled scout (`python agent.py`) is **not** a 24/7 polling host.
Run `python main.py` on a persistent server/container with outbound HTTPS and a
persistent writable volume for `BOT_DB_PATH`. Only **one** polling instance should
consume updates for a given bot token; disable any competing Telegram webhook.

## Configuration

Set the following in the hosting platform's secret manager (never commit secrets):

- `TELEGRAM_BOT_TOKEN`: token for `@mysoupsearchbot`.
- `TELEGRAM_ALLOWED_USER_IDS`: comma-separated permitted Telegram user IDs.
- `ADMIN_CHAT_ID`: admin **user ID**, required for `/status` and `/backup`.
- `BOT_DB_PATH`: absolute path on persistent storage, e.g. `/data/bot_sessions.db`.
- `GOOGLE_API_KEY`, `SEARCH_ENGINE_ID`: Google Programmable Search credentials.
- `GEMINI_API_KEY`: optional Gemini relevance screening; without it, the
  existing search pipeline fails closed.
- `TELEGRAM_BACKUP_CHANNEL_ID`: private vault channel ID; bot must be an
  administrator with document-posting and message-pinning rights.
- `BACKUP_ENCRYPTION_KEY`: a persistent Fernet key generated with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
  Store a separate recovery copy; rotating without retaining the old key
  makes earlier snapshots unrecoverable.

The search adapter only accepts explicitly licensed Internet Archive file
candidates; the search pipeline and live delivery are not fully integrated.
Never interpret an LLM's relevance score as proof of download safety or rights.

## Start and validate

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py
```

In a **private** Telegram conversation with the bot, test `/start`,
`/status`, and `/backup` using the configured admin account. Confirm
that another user cannot access diagnostics or backups. Confirm the backup
channel contains a new encrypted document **and** that the message is pinned.
Stop the process, restart it, and check that the persistent database remains
intact. Review hosting logs for crashes and restart loops.

The status command reports the uptime of the current polling process, not
the health of GitHub Actions or Telegram infrastructure. A green CI build
does not prove that the hosted process is online. Do not attempt live
Telegram verification using GitHub Actions secrets in pull requests.

## Recovery and rollout

The app deliberately does **not** auto-restore snapshots. With polling
stopped and after independently obtaining the encrypted snapshot from
the vault, restore to a **new** database path using:

```sh
python restore_db.py --encrypted-file /secure/sessions.snapshot.enc \
  --target /data/recovered_sessions.db --confirm-restore
```

Verify integrity and contents before switching `BOT_DB_PATH`. Keep the
previous database and encrypted backup until recovery is validated. Never
overwrite an existing database automatically.

If the process fails to start, inspect logs and verify the bot token, admin
allowlist, mounted volume permissions and absence of a competing poller.
