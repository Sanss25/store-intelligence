import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "/data/store_intelligence.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            event_id       TEXT PRIMARY KEY,
            store_id       TEXT NOT NULL,
            camera_id      TEXT,
            visitor_id     TEXT,
            event_type     TEXT NOT NULL,
            timestamp      TEXT NOT NULL,
            zone_id        TEXT,
            dwell_ms       INTEGER DEFAULT 0,
            is_staff       INTEGER DEFAULT 0,
            confidence     REAL DEFAULT 1.0,
            queue_depth    INTEGER,
            session_seq    INTEGER DEFAULT 1,
            raw_json       TEXT,
            ingested_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_events_store  ON events(store_id);
        CREATE INDEX IF NOT EXISTS idx_events_type   ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_ts     ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_vis    ON events(visitor_id);

        CREATE TABLE IF NOT EXISTS pos_transactions (
            transaction_id  TEXT PRIMARY KEY,
            store_id        TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            basket_value    REAL DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
