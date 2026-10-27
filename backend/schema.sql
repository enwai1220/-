CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY,
 date TEXT NOT NULL DEFAULT '',
 event TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT '',
 analysis TEXT NOT NULL DEFAULT '',
 engine TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','archived')),
 revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 archived_at TEXT,
 legacy_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS records_status ON records(status,created_at);
CREATE TABLE IF NOT EXISTS imports (digest TEXT PRIMARY KEY, imported_at TEXT NOT NULL, snapshot TEXT NOT NULL);
PRAGMA user_version=2;
