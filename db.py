"""SQLite persistence layer — tracks which items have already been emailed."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

DEFAULT_DB_PATH = Path(__file__).parent / "state.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    item_key     TEXT NOT NULL,
    title        TEXT,
    url          TEXT,
    item_date    TEXT,
    first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, item_key)
);

CREATE INDEX IF NOT EXISTS idx_seen_source ON seen_items(source);
CREATE INDEX IF NOT EXISTS idx_seen_first_seen ON seen_items(first_seen);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT NOT NULL UNIQUE,
    items_sent   INTEGER NOT NULL DEFAULT 0,
    finished_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect(db_path: Path = DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def already_seen(conn: sqlite3.Connection, source: str, item_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen_items WHERE source = ? AND item_key = ? LIMIT 1",
        (source, item_key),
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, source: str, item_key: str, title: str, url: str, item_date: str | None) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO seen_items (source, item_key, title, url, item_date)
           VALUES (?, ?, ?, ?, ?)""",
        (source, item_key, title, url, item_date),
    )


def record_run(conn: sqlite3.Connection, run_date: str, items_sent: int) -> None:
    conn.execute(
        """INSERT INTO runs (run_date, items_sent) VALUES (?, ?)
           ON CONFLICT(run_date) DO UPDATE SET items_sent = excluded.items_sent,
                                               finished_at = datetime('now')""",
        (run_date, items_sent),
    )


def has_run_today(conn: sqlite3.Connection, run_date: str) -> bool:
    row = conn.execute("SELECT 1 FROM runs WHERE run_date = ? LIMIT 1", (run_date,)).fetchone()
    return row is not None
