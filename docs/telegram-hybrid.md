# msasoup hybrid mode

The persistent `main.py` listener owns incoming messages, callback handling,
interactive searches and the private SQLite session database. GitHub Actions
continues the existing daily `agent.py` licensed-book delivery. The daily job
is an outbound producer, never a second getUpdates consumer. No sessions or
private database are transferred to public workflow inputs or runner backups.

The listener processes up to eight updates concurrently, with a separate lock
per allowlisted user to preserve session ordering. Other users and the
independent admin status handler can progress while a search awaits its worker.
This does not offload private interactive sessions to Actions. A burst that
occupies all eight slots can still delay updates; no unbounded concurrency is
claimed. Existing session integrity, identity and webhook checks remain active.

Use the runtime repair's persistent service and existing host credentials.
Review and integrate conversational PR #12 before replacing a feature-branch
host; this repair does not silently replace that deployed feature source.
Keep exactly one listener, retain the session database, and leave the daily
workflow enabled only for the intended destination. No new paid API, server or
runner plan is introduced. A live host and real replies are still unverified.

Acceptance: confirm a search plus concurrent admin status, same-user ordered
callbacks, another allowed user's progress, scheduled delivery, and restart
with the same session DB. The source tests exercise concurrency and ordering;
production network/hosting verification remains a separate gate.

## Source verification

Full local regression suite: **120 passed, zero failures**. Source compilation,
workflow/dispatch contract validation (where changed) and diff checks passed.
The live host, actual dispatch credentials, Telegram replies and deployment
cutover have not been verified. These counts do not claim production activation.
