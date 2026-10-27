CREATE TABLE IF NOT EXISTS task_triage (
 id INTEGER PRIMARY KEY CHECK(id=1), input TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
 result TEXT, result_input TEXT NOT NULL DEFAULT '', analyzed_at TEXT
);
CREATE TABLE IF NOT EXISTS triage_archives (
 id TEXT PRIMARY KEY, archived_at TEXT NOT NULL, input TEXT NOT NULL, result TEXT NOT NULL,
 result_input TEXT NOT NULL, analyzed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS triage_archives_time ON triage_archives(archived_at);
CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, migrated_at TEXT NOT NULL);
PRAGMA user_version=1;
