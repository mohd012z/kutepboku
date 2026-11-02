-- Draft-only D1 schema for the Telegram webhook inbox and delivery outbox.
-- Apply explicitly in staging after reviewing existing D1 tables; never auto-apply to production.
CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id INTEGER PRIMARY KEY CHECK (update_id >= 0),
    status TEXT NOT NULL CHECK (status IN ('received', 'sent'))
);

CREATE TABLE IF NOT EXISTS telegram_outbox (
    id INTEGER PRIMARY KEY,
    update_id INTEGER NOT NULL UNIQUE REFERENCES telegram_updates(update_id) ON DELETE RESTRICT,
    chat_id TEXT NOT NULL CHECK (length(chat_id) > 0),
    reply_text TEXT NOT NULL CHECK (length(reply_text) > 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'sending', 'uncertain', 'sent')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS idx_telegram_outbox_status
    ON telegram_outbox(status, id);
