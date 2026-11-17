CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
 chat_id INTEGER NOT NULL,
 payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','dead')),
 attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt INTEGER NOT NULL DEFAULT 0,
 lease_token TEXT,
 lease_until INTEGER,
 last_error TEXT,
 sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox(status,next_attempt,lease_until,id);
