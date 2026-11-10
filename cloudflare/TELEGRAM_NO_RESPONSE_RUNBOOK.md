# MSASoup Telegram no-response incident: safe verification gate

Scope: `@mysoupsearchbot`, Cloudflare Worker `msasoup-telegram`, and the separate Python polling bot. This document does **not** authorize a production webhook cutover.

## Verified as of 2026-11-03

- Deployed Worker version: `72c81fe8-183e-4ded-b8ea-e103c041ddc1` (2026-11-01 deployment).
- Worker URL: `https://msasoup-telegram.ifxhelper.workers.dev/telegram`.
- Cloudflare settings contain D1 `DB` and secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_ALLOWED_USER_IDS`. Secret **values and correctness have not been verified**.
- D1 `telegram_updates` count: **0**; required tables and columns exist.
- Deployed Worker source is older than the branch implementation and acknowledges certain delivery failures with HTTP 200.
- `main.py` starts a polling bot; `cloudflare/src/worker.js` expects webhook updates.
- Live Telegram bot identity, registered webhook URL, Telegram delivery errors, user allowlist match, and an actual command round trip remain **unverified**.

## Read-only diagnosis (never paste or log a token)

Run from a trusted environment with the bot token in an environment secret. Print **only** sanitized fields. Do not store the token in a repository or shell history.

1. Call Telegram `getMe` and compare `result.username` with `mysoupsearchbot`; stop if different.
2. Call Telegram `getWebhookInfo`; record only `url`, `pending_update_count`, `last_error_date`, `last_error_message`, `max_connections`, and `allowed_updates`. Do not print full API request URLs.
3. If `url` is empty, the bot is not currently webhook-driven. Inspect the active Python polling process before changing anything.
4. If `url` differs from the intended Worker URL, identify the current owner and its rollback path before any cutover.
5. If `url` matches, inspect recent Cloudflare requests for `/telegram`, including status codes, without logging request bodies, user IDs, or secrets.
6. Send a private `/menu` from an approved Telegram user, and correlate the time with the Worker request and D1 `telegram_updates` row. A row count of zero after the test means no authorized recognized update was persisted; it does **not** distinguish missing delivery, invalid webhook secret, and allowlist mismatch.
7. If requests return 401, check webhook-secret parity; 503, check bindings and D1 errors; 200 with no D1 row, check actor allowlist and unsupported command handling.
8. Do not run `setWebhook`, `deleteWebhook`, `getUpdates`, or deploy to production until token identity and ownership are verified and a rollback is documented.

## Release gates

- Node Worker test suite PASS with real workflow job evidence.
- Staging Worker with isolated credentials and D1 PASS.
- `getMe` identity and `getWebhookInfo` ownership recorded.
- Private `/start` and `/menu` plus one callback deliver replies; confirm one outbox row per update.
- Explicit approval for production cutover; preserve main and RM0 billing.
- Verify rollback and no duplicate delivery before closing incident.

**Do not confuse a configured secret name, a healthy D1 query, or a successful deployment with a proven Telegram reply.**
