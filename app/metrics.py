from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/metrics")
def get_metrics(store_id: str, window_hours: int = 24):
    """
    Real-time store metrics for today's window.
    Excludes is_staff=1 from all customer metrics.
    """
    store_id = store_id.upper()
    conn = get_conn()
    try:
        # ── Unique visitors (non-staff ENTRY events, deduplicated by visitor_id)
        row = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as unique_visitors
            FROM events
            WHERE store_id = ?
              AND event_type IN ('ENTRY','REENTRY')
              AND is_staff = 0
              AND visitor_id IS NOT NULL
        """, (store_id,)).fetchone()
        unique_visitors = row["unique_visitors"] if row else 0

        # ── Current occupancy: entries - exits (non-staff)
        entries = conn.execute("""
            SELECT COUNT(*) as c FROM events
            WHERE store_id=? AND event_type='ENTRY' AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        exits = conn.execute("""
            SELECT COUNT(*) as c FROM events
            WHERE store_id=? AND event_type='EXIT' AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        occupancy = max(0, entries - exits)

        # ── Avg dwell per zone
        zone_rows = conn.execute("""
            SELECT zone_id,
                   AVG(dwell_ms) as avg_dwell_ms,
                   COUNT(*) as visits
            FROM events
            WHERE store_id=? AND event_type IN ('ZONE_DWELL','ZONE_EXIT','ZONE_EXITED')
              AND is_staff=0 AND zone_id IS NOT NULL AND dwell_ms > 0
            GROUP BY zone_id
        """, (store_id,)).fetchall()
        avg_dwell_per_zone = {
            r["zone_id"]: {
                "avg_dwell_ms": round(r["avg_dwell_ms"]),
                "visits": r["visits"]
            }
            for r in zone_rows
        }

        # ── Queue depth (latest queue_depth value)
        qrow = conn.execute("""
            SELECT queue_depth FROM events
            WHERE store_id=? AND queue_depth IS NOT NULL
            ORDER BY timestamp DESC LIMIT 1
        """, (store_id,)).fetchone()
        queue_depth = qrow["queue_depth"] if qrow else 0

        # ── Abandonment rate
        abandoned = conn.execute("""
            SELECT COUNT(*) as c FROM events
            WHERE store_id=? AND event_type IN ('BILLING_QUEUE_ABANDON','QUEUE_ABANDONED')
              AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        billing_joins = conn.execute("""
            SELECT COUNT(*) as c FROM events
            WHERE store_id=? AND event_type IN ('BILLING_QUEUE_JOIN','QUEUE_COMPLETED','QUEUE_ABANDONED')
              AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        abandonment_rate = round(abandoned / billing_joins, 4) if billing_joins > 0 else 0.0

        # ── Conversion rate: visitors who reached billing / total visitors
        billing_visitors = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c FROM events
            WHERE store_id=? AND event_type IN ('BILLING_QUEUE_JOIN','QUEUE_COMPLETED','QUEUE_ABANDONED')
              AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        conversion_rate = round(billing_visitors / unique_visitors, 4) if unique_visitors > 0 else 0.0

        return {
            "store_id": store_id,
            "unique_visitors": unique_visitors,
            "occupancy": occupancy,
            "entries": entries,
            "exits": exits,
            "conversion_rate": conversion_rate,
            "avg_dwell_per_zone": avg_dwell_per_zone,
            "queue_depth": queue_depth,
            "abandonment_rate": abandonment_rate,
        }
    finally:
        conn.close()
