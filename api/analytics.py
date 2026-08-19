"""Metrics, funnel, heatmap and anomaly computations.

All functions take a live sqlite3.Connection and a store_id, and run
plain SQL aggregations. No caching layer — event volume for a single
store's camera feed is small enough that this is fast; if this needed
to scale to hundreds of stores, this is the first place to add
materialized rollups (see docs/CHOICES.md).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

FUNNEL_STAGES = [
    ("Entry", ["ENTRY"]),
    ("Zone visit", ["ZONE_ENTER"]),
    ("Queue", ["QUEUE_JOIN"]),
    ("Purchase", ["PURCHASE"]),
]

STALE_FEED_MINUTES = 15
QUEUE_SPIKE_DEPTH = 5
DEAD_ZONE_WINDOW_HOURS = 24
CONVERSION_DROP_PCT = 0.5  # flag if conversion falls below 50% of baseline


def get_metrics(conn: sqlite3.Connection, store_id: str) -> dict:
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT visitor_id) AS unique_visitors,
            SUM(CASE WHEN event_type = 'ENTRY' THEN 1 ELSE 0 END) AS entries,
            SUM(CASE WHEN event_type = 'EXIT' THEN 1 ELSE 0 END) AS exits,
            SUM(CASE WHEN event_type = 'PURCHASE' THEN 1 ELSE 0 END) AS purchases,
            AVG(CASE WHEN dwell_ms > 0 THEN dwell_ms END) AS avg_dwell_ms,
            MIN(timestamp) AS window_start,
            MAX(timestamp) AS window_end
        FROM events
        WHERE store_id = ?
        """,
        (store_id,),
    ).fetchone()

    entries = row["entries"] or 0
    exits = row["exits"] or 0
    purchases = row["purchases"] or 0

    queue_row = conn.execute(
        """
        SELECT queue_depth FROM events
        WHERE store_id = ? AND queue_depth IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
        """,
        (store_id,),
    ).fetchone()

    return {
        "store_id": store_id,
        "unique_visitors": row["unique_visitors"] or 0,
        "occupancy": max(0, entries - exits),
        "entries": entries,
        "exits": exits,
        "purchases": purchases,
        "conversion_rate": round((purchases / entries * 100), 2) if entries else 0.0,
        "avg_dwell_ms": round(row["avg_dwell_ms"] or 0.0, 2),
        "current_queue_depth": queue_row["queue_depth"] if queue_row else 0,
        "window_start": row["window_start"],
        "window_end": row["window_end"],
    }


def get_funnel(conn: sqlite3.Connection, store_id: str) -> dict:
    stages = []
    base_visitors = None
    for stage_name, event_types in FUNNEL_STAGES:
        placeholders = ",".join("?" for _ in event_types)
        row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT visitor_id) AS visitors
            FROM events
            WHERE store_id = ? AND event_type IN ({placeholders})
            """,
            (store_id, *event_types),
        ).fetchone()
        visitors = row["visitors"] or 0
        if base_visitors is None:
            base_visitors = visitors or 1  # avoid div by zero
        dropoff_pct = round(100 * (1 - visitors / base_visitors), 2) if base_visitors else 0.0
        stages.append({"stage": stage_name, "visitors": visitors, "dropoff_pct": dropoff_pct})

    return {"store_id": store_id, "stages": stages}


def get_heatmap(conn: sqlite3.Connection, store_id: str) -> dict:
    rows = conn.execute(
        """
        SELECT zone_id, COUNT(*) AS visits, AVG(CASE WHEN dwell_ms > 0 THEN dwell_ms END) AS avg_dwell_ms
        FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL
        GROUP BY zone_id
        """,
        (store_id,),
    ).fetchall()

    if not rows:
        return {"store_id": store_id, "zones": []}

    max_visits = max(r["visits"] for r in rows) or 1
    zones = []
    for r in rows:
        heat_score = round(100 * (r["visits"] / max_visits), 2)
        zones.append(
            {
                "zone_id": r["zone_id"],
                "visits": r["visits"],
                "avg_dwell_ms": round(r["avg_dwell_ms"] or 0.0, 2),
                "heat_score": heat_score,
            }
        )
    return {"store_id": store_id, "zones": zones}


def get_anomalies(conn: sqlite3.Connection, store_id: str) -> dict:
    anomalies = []
    now = datetime.now(timezone.utc)

    # STALE_FEED: no events recently
    last_row = conn.execute(
        "SELECT MAX(timestamp) AS last_ts FROM events WHERE store_id = ?",
        (store_id,),
    ).fetchone()
    if last_row and last_row["last_ts"]:
        last_ts = _parse_ts(last_row["last_ts"])
        if last_ts and (now - last_ts) > timedelta(minutes=STALE_FEED_MINUTES):
            anomalies.append(
                {
                    "type": "STALE_FEED",
                    "severity": "high",
                    "message": f"No events from {store_id} in over {STALE_FEED_MINUTES} minutes.",
                    "detected_at": now.isoformat(),
                }
            )

    # QUEUE_SPIKE: latest queue_depth above threshold
    queue_row = conn.execute(
        """
        SELECT queue_depth FROM events
        WHERE store_id = ? AND queue_depth IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
        """,
        (store_id,),
    ).fetchone()
    if queue_row and queue_row["queue_depth"] and queue_row["queue_depth"] >= QUEUE_SPIKE_DEPTH:
        anomalies.append(
            {
                "type": "QUEUE_SPIKE",
                "severity": "medium",
                "message": f"Queue depth at {queue_row['queue_depth']}, at/above threshold of {QUEUE_SPIKE_DEPTH}.",
                "detected_at": now.isoformat(),
            }
        )

    # DEAD_ZONE: zones with entries but zero recent visits
    cutoff = (now - timedelta(hours=DEAD_ZONE_WINDOW_HOURS)).isoformat()
    dead_zones = conn.execute(
        """
        SELECT DISTINCT zone_id FROM events
        WHERE store_id = ? AND zone_id IS NOT NULL
        AND zone_id NOT IN (
            SELECT DISTINCT zone_id FROM events
            WHERE store_id = ? AND zone_id IS NOT NULL AND timestamp >= ?
        )
        """,
        (store_id, store_id, cutoff),
    ).fetchall()
    for z in dead_zones:
        anomalies.append(
            {
                "type": "DEAD_ZONE",
                "severity": "low",
                "message": f"Zone {z['zone_id']} has had no visits in the last {DEAD_ZONE_WINDOW_HOURS}h.",
                "detected_at": now.isoformat(),
            }
        )

    # CONVERSION_DROP: compare last-hour conversion to all-time baseline
    metrics = get_metrics(conn, store_id)
    recent_cutoff = (now - timedelta(hours=1)).isoformat()
    recent_row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN event_type = 'ENTRY' THEN 1 ELSE 0 END) AS entries,
            SUM(CASE WHEN event_type = 'PURCHASE' THEN 1 ELSE 0 END) AS purchases
        FROM events WHERE store_id = ? AND timestamp >= ?
        """,
        (store_id, recent_cutoff),
    ).fetchone()
    recent_entries = recent_row["entries"] or 0
    recent_purchases = recent_row["purchases"] or 0
    if recent_entries >= 5 and metrics["conversion_rate"] > 0:
        recent_conv = recent_purchases / recent_entries * 100
        if recent_conv < metrics["conversion_rate"] * CONVERSION_DROP_PCT:
            anomalies.append(
                {
                    "type": "CONVERSION_DROP",
                    "severity": "medium",
                    "message": f"Last-hour conversion ({recent_conv:.1f}%) is well below baseline ({metrics['conversion_rate']:.1f}%).",
                    "detected_at": now.isoformat(),
                }
            )

    return {"store_id": store_id, "anomalies": anomalies}


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None
