# Persistent Telegram listener repair

## Scope and current evidence

The source repair is tested locally. No persistent host, bot credentials, live
webhook registration, or live Telegram reply was available in this session.
Installing a service file does not prove the bot is online. GitHub Actions
success proves a job completed, not continuous listening.

## Cutover on an existing Linux host

Use the existing host, not this transient development workspace. Do not create
a paid service for this repair. Provision a `telegram-bots` service user, place
the tested checkout at `/opt/telegram-bots/kutepboku`, and install its dependencies.
For Python repositories create `.venv`; for BizCrax36 the listener is stdlib-only.
Keep credentials in `/etc/telegram-bots/kutepboku.env` (root-owned, mode 0600),
never in git or shell history. The service file has concrete paths and no
embedded credentials.

Required host environment: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`
(comma-separated numeric user IDs), and optionally `ADMIN_CHAT_ID` for private
admin `/status` and `/backup`. Keep the existing database; copy it only while
the previous process is stopped, with backup and integrity checks first.
The daily `agent.py` workflow is outbound delivery, not an interactive listener;
keep it separate. This service starts `main.py` and preserves pending updates.
The local lock blocks a second copy. An existing webhook or wrong bot identity
stops startup; a polling conflict stops the application with exit 78.

This patch targets `main`; it does not merge PR #12's conversational feature
changes or confirm that a separately deployed feature branch is synchronized.
Rebase this repair onto the actual deployed source before upgrading that host.


Stop every other consumer of this same bot token, including processes on
other hosts, before activation. Local locks cannot prevent cross-host conflicts.
Do not delete an existing webhook automatically. Confirm its owner and stop
it as part of an intentional cutover. Do not drop pending updates.

Copy `deploy/telegram-msasoup.service` into `/etc/systemd/system/`, then run
`systemctl daemon-reload` and `systemctl enable --now telegram-msasoup` on that host.
For BizCrax36, grant the service user ownership of the checkout's `data/`;
for msasoup grant ownership of `logs/`. systemd creates the private state
directory and restarts transient crashes. Configuration exit 78 stays stopped
so conflicts and credential errors are visible rather than retried forever.
Review `systemctl status telegram-msasoup` and `journalctl -u telegram-msasoup`.

## Required live acceptance

- Service stays active across a host reboot and a transient network failure.
- An authorized `/start` (or existing BBMA callback for Helix) receives the
  correct response; unauthorized access remains denied.
- No Telegram 409 conflicts or webhook replacement occurs.
- State survives a graceful restart; pending updates are retained.
- A second local process fails immediately without stealing updates.
- Confirm the host uses this exact reviewed commit and the expected bot identity.

## Rollback

Stop the new service first. Restore the previous host configuration and saved
database if necessary. For Actions-owned consumers only, restore repository
variable `TELEGRAM_RUNTIME=actions` after the persistent service is stopped.
Do not run both modes as a fallback race.

## Local verification, 28 October 2026

`python3 -W error::ResourceWarning -m unittest discover -s tests -q`: **119 passed, zero failures**. Python compilation / Node syntax
checks and `git diff --check` passed. Service unit syntax was checked with
`systemd-analyze verify` using temporary copies whose Python executable paths
were substituted for the available interpreter. The real deployment paths,
service user, credentials, host reboot/restart behavior, ledger freshness, and
live Telegram replies remain **unverified**. No paid service was enabled and no
production webhook or deployment was changed.
