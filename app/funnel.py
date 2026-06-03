from fastapi import APIRouter
from app.database import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/funnel")
def get_funnel(store_id: str):
    """
    Conversion funnel: Entry → Zone Visit → Billing Queue → Purchase
    Session is the unit. Re-entries do not double-count a visitor.
    """
    store_id = store_id.upper()
    conn = get_conn()
    try:
        # Stage 1: unique customer visitors (distinct visitor_id with ENTRY)
        entered = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events
            WHERE store_id=? AND event_type='ENTRY' AND is_staff=0
              AND visitor_id IS NOT NULL
        """, (store_id,)).fetchone()["c"]

        # Stage 2: visitors who entered at least one zone
        zone_visitors = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events
            WHERE store_id=? AND event_type IN ('ZONE_ENTER','ZONE_ENTERED')
              AND is_staff=0 AND visitor_id IS NOT NULL
        """, (store_id,)).fetchone()["c"]

        # Stage 3: visitors who reached billing queue
        billing_visitors = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events
            WHERE store_id=? 
              AND event_type IN ('BILLING_QUEUE_JOIN','QUEUE_COMPLETED','QUEUE_ABANDONED')
              AND is_staff=0 AND visitor_id IS NOT NULL
        """, (store_id,)).fetchone()["c"]

        # Stage 4: visitors who completed purchase (queue_completed = not abandoned)
        purchased = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events
            WHERE store_id=?
              AND event_type IN ('BILLING_QUEUE_JOIN','QUEUE_COMPLETED')
              AND is_staff=0 AND visitor_id IS NOT NULL
        """, (store_id,)).fetchone()["c"]

        def pct(num, denom):
            return round(num / denom * 100, 1) if denom > 0 else 0.0

        def dropoff(a, b):
            return round((a - b) / a * 100, 1) if a > 0 else 0.0

        stages = [
            {
                "stage": "entry",
                "label": "Store Entry",
                "count": entered,
                "pct_of_top": 100.0,
                "dropoff_pct": dropoff(entered, zone_visitors),
            },
            {
                "stage": "zone_visit",
                "label": "Zone Visit",
                "count": zone_visitors,
                "pct_of_top": pct(zone_visitors, entered),
                "dropoff_pct": dropoff(zone_visitors, billing_visitors),
            },
            {
                "stage": "billing_queue",
                "label": "Billing Queue",
                "count": billing_visitors,
                "pct_of_top": pct(billing_visitors, entered),
                "dropoff_pct": dropoff(billing_visitors, purchased),
            },
            {
                "stage": "purchase",
                "label": "Purchase Completed",
                "count": purchased,
                "pct_of_top": pct(purchased, entered),
                "dropoff_pct": 0.0,
            },
        ]

        return {
            "store_id": store_id,
            "overall_conversion_rate": pct(purchased, entered),
            "stages": stages,
        }
    finally:
        conn.close()
