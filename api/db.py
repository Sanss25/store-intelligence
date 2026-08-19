"""SQLite persistence layer for Store Intelligence.

Kept as raw sqlite3 (no ORM) deliberately: the event volume here is
small, the query surface is simple, and it makes the whole thing
runnable with zero extra dependencies / zero external DB service.
See docs/CHOICES.md for the full rationale.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

DB_PATH = os.environ.get("STORE_INTEL_DB", "store_intel.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id      TEXT PRIMARY KEY,
    store_id      TEXT NOT NULL,
    camera_id     TEXT NOT NULL,
    visitor_id    TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    zone_id       TEXT,
    dwell_ms      INTEGER DEFAULT 0,
    is_staff      INTEGER DEFAULT 0,
    confidence    REAL DEFAULT 0.9,
    queue_depth   INTEGER,
    session_seq   INTEGER DEFAULT 1,
    ingested_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_store ON events(store_id);
CREATE INDEX IF NOT EXISTS idx_events_store_type ON events(store_id, event_type);
CREATE INDEX IF NOT EXISTS idx_events_store_zone ON events(store_id, zone_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
"""


def init_db(db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def insert_event(conn: sqlite3.Connection, event: dict) -> bool:
    """Idempotent insert. Returns True if a new row was created."""
    meta = event.get("metadata") or {}
    try:
        conn.execute(
            """
            INSERT INTO events (
                event_id, store_id, camera_id, visitor_id, event_type,
                timestamp, zone_id, dwell_ms, is_staff, confidence,
                queue_depth, session_seq, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["store_id"],
                event["camera_id"],
                event["visitor_id"],
                event["event_type"],
                event["timestamp"],
                event.get("zone_id"),
                event.get("dwell_ms", 0),
                int(bool(event.get("is_staff", False))),
                event.get("confidence", 0.9),
                meta.get("queue_depth"),
                meta.get("session_seq", 1),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # event_id already exists -> duplicate, ingestion stays idempotent
        return False


def count_events(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
