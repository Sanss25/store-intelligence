from fastapi import APIRouter
from datetime import datetime, UTC, timedelta
from app.database import get_conn

router = APIRouter()

STALE_THRESHOLD_MINUTES = 10


@router.get("/health")
def health():
    conn = get_conn()
    now = datetime.now(UTC)
    try:
        store_rows = conn.execute("""
            SELECT store_id,
                   MAX(timestamp) as last_event_ts,
                   COUNT(*) as total_events
            FROM events
            GROUP BY store_id
        """).fetchall()

        stores = {}
        for r in store_rows:
            last_ts = r["last_event_ts"]
            status = "OK"
            lag_minutes = None
            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    lag_minutes = round((now - last_dt).total_seconds() / 60, 1)
                    if lag_minutes > STALE_THRESHOLD_MINUTES:
                        status = "STALE_FEED"
                except Exception:
                    status = "UNKNOWN"
            stores[r["store_id"]] = {
                "status": status,
                "last_event_timestamp": last_ts,
                "lag_minutes": lag_minutes,
                "total_events_ingested": r["total_events"],
            }

        total_events = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]

        return {
            "status": "OK",
            "version": "1.0.0",
            "checked_at": now.isoformat(),
            "total_events_ingested": total_events,
            "stores": stores,
        }
    except Exception as e:
        return {
            "status": "DEGRADED",
            "error": str(e),
            "checked_at": now.isoformat(),
        }
    finally:
        conn.close()
