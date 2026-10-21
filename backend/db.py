"""SQLite storage: users, voice profiles, drafts with version history, and suggestion feedback."""
import json
import sqlite3
import time
from contextlib import contextmanager

from config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    samples TEXT NOT NULL,      -- JSON list of essay texts
    stats TEXT NOT NULL,        -- JSON style statistics
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY,
    draft_id INTEGER NOT NULL REFERENCES drafts(id),
    body TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL
);
-- Every accept/reject is kept: accepted edits become fine-tuning data later.
-- draft_id ties it to its essay so deleting the essay deletes this too.
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    draft_id INTEGER REFERENCES drafts(id),
    original TEXT NOT NULL,
    revised TEXT NOT NULL,
    reason TEXT NOT NULL,
    category TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    created REAL NOT NULL
);
"""


def init():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        migrate(conn)


def migrate(conn):
    """Brings databases created by older versions up to the current schema."""
    feedback_columns = {row["name"] for row in conn.execute("PRAGMA table_info(feedback)")}
    if "draft_id" not in feedback_columns:
        conn.execute("ALTER TABLE feedback ADD COLUMN draft_id INTEGER REFERENCES drafts(id)")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now():
    return time.time()


def loads(value):
    return json.loads(value) if value else None
