from fastapi import APIRouter
from datetime import datetime, UTC, timedelta
from app.database import get_conn

router = APIRouter()

QUEUE_SPIKE_THRESHOLD = 5      # queue_depth that triggers WARN
QUEUE_CRITICAL_THRESHOLD = 10
DEAD_ZONE_MINUTES = 30
CONVERSION_DROP_THRESHOLD = 0.3  # 30% below baseline triggers WARN


@router.get("/stores/{store_id}/anomalies")
def get_anomalies(store_id: str):
    store_id = store_id.upper()
    conn = get_conn()
    anomalies = []

    try:
        now = datetime.now(UTC)

        # ── 1. Queue spike
        qrow = conn.execute("""
            SELECT queue_depth, timestamp FROM events
            WHERE store_id=? AND queue_depth IS NOT NULL
            ORDER BY timestamp DESC LIMIT 1
        """, (store_id,)).fetchone()

        if qrow and qrow["queue_depth"] is not None:
            qd = qrow["queue_depth"]
            if qd >= QUEUE_CRITICAL_THRESHOLD:
                anomalies.append({
                    "anomaly_type": "BILLING_QUEUE_SPIKE",
                    "severity": "CRITICAL",
                    "value": qd,
                    "threshold": QUEUE_CRITICAL_THRESHOLD,
                    "detected_at": qrow["timestamp"],
                    "suggested_action": "Open additional billing counter immediately. Queue is critically deep.",
                })
            elif qd >= QUEUE_SPIKE_THRESHOLD:
                anomalies.append({
                    "anomaly_type": "BILLING_QUEUE_SPIKE",
                    "severity": "WARN",
                    "value": qd,
                    "threshold": QUEUE_SPIKE_THRESHOLD,
                    "detected_at": qrow["timestamp"],
                    "suggested_action": "Consider opening a second billing counter. Queue depth elevated.",
                })

        # ── 2. Dead zones (no zone events in last 30 min)
        cutoff = (now - timedelta(minutes=DEAD_ZONE_MINUTES)).isoformat()
        active_zones = conn.execute("""
            SELECT DISTINCT zone_id FROM events
            WHERE store_id=? AND zone_id IS NOT NULL
              AND timestamp > ?
        """, (store_id, cutoff)).fetchall()
        active_zone_ids = {r["zone_id"] for r in active_zones}

        all_zones = conn.execute("""
            SELECT DISTINCT zone_id FROM events
            WHERE store_id=? AND zone_id IS NOT NULL
        """, (store_id,)).fetchall()

        for row in all_zones:
            if row["zone_id"] not in active_zone_ids:
                anomalies.append({
                    "anomaly_type": "DEAD_ZONE",
                    "severity": "INFO",
                    "zone_id": row["zone_id"],
                    "no_activity_minutes": DEAD_ZONE_MINUTES,
                    "detected_at": now.isoformat(),
                    "suggested_action": f"Zone {row['zone_id']} has had no visitors for {DEAD_ZONE_MINUTES}+ minutes. Check camera or restock.",
                })

        # ── 3. Conversion drop vs baseline
        # Baseline: overall conversion rate
        total_visitors = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events WHERE store_id=? AND event_type='ENTRY' AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        billing_visitors = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events WHERE store_id=?
              AND event_type IN ('BILLING_QUEUE_JOIN','QUEUE_COMPLETED','QUEUE_ABANDONED')
              AND is_staff=0
        """, (store_id,)).fetchone()["c"]

        if total_visitors > 10:
            conv_rate = billing_visitors / total_visitors
            # Simple heuristic: flag if below 10% (beauty retail baseline ~20-30%)
            if conv_rate < 0.10:
                anomalies.append({
                    "anomaly_type": "CONVERSION_DROP",
                    "severity": "WARN",
                    "current_conversion_rate": round(conv_rate, 4),
                    "baseline": 0.20,
                    "detected_at": now.isoformat(),
                    "suggested_action": "Conversion rate below 10%. Consider staff engagement or promotional push.",
                })

        # ── 4. Stale feed (no events in last 10 min)
        last_event = conn.execute("""
            SELECT MAX(timestamp) as last_ts FROM events WHERE store_id=?
        """, (store_id,)).fetchone()["last_ts"]

        if last_event:
            try:
                last_dt = datetime.fromisoformat(last_event.replace("Z", "+00:00"))
                lag_minutes = (now - last_dt).total_seconds() / 60
                if lag_minutes > 10:
                    anomalies.append({
                        "anomaly_type": "STALE_FEED",
                        "severity": "CRITICAL",
                        "lag_minutes": round(lag_minutes, 1),
                        "last_event_at": last_event,
                        "detected_at": now.isoformat(),
                        "suggested_action": "Camera feed appears stale. Check pipeline connectivity.",
                    })
            except Exception:
                pass

        return {
            "store_id": store_id,
            "checked_at": now.isoformat(),
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
        }
    finally:
        conn.close()
