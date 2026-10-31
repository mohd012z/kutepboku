CREATE TABLE IF NOT EXISTS webhook_inbox (
 update_id INTEGER PRIMARY KEY,
 payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','done','uncertain')),
 attempts INTEGER NOT NULL DEFAULT 0,
 lease_token TEXT,
 lease_until INTEGER,
 last_error TEXT,
 received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_webhook_inbox_status ON webhook_inbox(status,update_id);
