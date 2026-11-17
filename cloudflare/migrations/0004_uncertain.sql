-- D1 migrations are executed transactionally by the migration runner.
-- Do not embed BEGIN/COMMIT or toggle foreign_keys inside a D1 migration.
CREATE TABLE outbox_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
 chat_id INTEGER NOT NULL,
 payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','dead','uncertain')),
 attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt INTEGER NOT NULL DEFAULT 0,
 lease_token TEXT,
 lease_until INTEGER,
 last_error TEXT,
 sent_at TEXT
);
INSERT INTO outbox_new (id,job_id,chat_id,payload,status,attempts,next_attempt,lease_token,lease_until,last_error,sent_at)
SELECT id,job_id,chat_id,payload,status,attempts,next_attempt,lease_token,lease_until,last_error,sent_at FROM outbox;
DROP TABLE outbox;
ALTER TABLE outbox_new RENAME TO outbox;
CREATE INDEX idx_outbox_claim ON outbox(status,next_attempt,lease_until,id);
