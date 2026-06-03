from fastapi import APIRouter
from app.database import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/heatmap")
def get_heatmap(store_id: str):
    """
    Zone visit frequency + avg dwell, normalised 0–100.
    Includes data_confidence flag if fewer than 20 sessions in window.
    """
    store_id = store_id.upper()
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT zone_id,
                   COUNT(DISTINCT visitor_id)  as unique_visitors,
                   COUNT(*)                    as total_visits,
                   AVG(dwell_ms)               as avg_dwell_ms,
                   MAX(dwell_ms)               as max_dwell_ms
            FROM events
            WHERE store_id=?
              AND event_type IN ('ZONE_DWELL','ZONE_EXIT','ZONE_EXITED','ZONE_ENTER','ZONE_ENTERED')
              AND is_staff=0
              AND zone_id IS NOT NULL
            GROUP BY zone_id
        """, (store_id,)).fetchall()

        if not rows:
            return {
                "store_id": store_id,
                "data_confidence": "LOW",
                "zones": [],
                "note": "No zone data ingested yet",
            }

        max_visits = max(r["total_visits"] for r in rows) or 1
        max_dwell = max(r["avg_dwell_ms"] or 0 for r in rows) or 1

        total_sessions = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events WHERE store_id=? AND event_type='ENTRY' AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        zones = []
        for r in rows:
            visit_score = round((r["total_visits"] / max_visits) * 100)
            dwell_score = round(((r["avg_dwell_ms"] or 0) / max_dwell) * 100)
            heat_score = round((visit_score + dwell_score) / 2)
            zones.append({
                "zone_id": r["zone_id"],
                "unique_visitors": r["unique_visitors"],
                "total_visits": r["total_visits"],
                "avg_dwell_ms": round(r["avg_dwell_ms"] or 0),
                "visit_score": visit_score,
                "dwell_score": dwell_score,
                "heat_score": heat_score,
            })

        zones.sort(key=lambda z: z["heat_score"], reverse=True)

        return {
            "store_id": store_id,
            "data_confidence": "LOW" if total_sessions < 20 else "HIGH",
            "total_sessions": total_sessions,
            "zones": zones,
        }
    finally:
        conn.close()
