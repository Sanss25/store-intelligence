import json
import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.models import IngestBatch, IngestEvent
from app.database import get_conn

router = APIRouter()
logger = logging.getLogger("store_intelligence")

VALID_EVENT_TYPES = {
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
    # also accept the sample schema variants
    "ENTRY", "EXIT", "ZONE_ENTERED", "ZONE_EXITED",
    "QUEUE_COMPLETED", "QUEUE_ABANDONED",
}


def _normalise(ev: IngestEvent) -> dict:
    meta = ev.metadata or {}
    meta_dict = meta.model_dump() if hasattr(meta, "model_dump") else {}
    return {
        "event_id":   ev.event_id,
        "store_id":   ev.store_id.upper(),
        "camera_id":  ev.camera_id,
        "visitor_id": ev.visitor_id,
        "event_type": ev.event_type,
        "timestamp":  ev.timestamp,
        "zone_id":    ev.zone_id,
        "dwell_ms":   ev.dwell_ms,
        "is_staff":   int(ev.is_staff),
        "confidence": ev.confidence,
        "queue_depth": meta_dict.get("queue_depth"),
        "session_seq": meta_dict.get("session_seq", 1),
        "raw_json":   ev.model_dump_json(),
    }


@router.post("/events/ingest", status_code=200)
def ingest_events(batch: IngestBatch):
    """
    Accepts up to 500 events per call.
    Idempotent: duplicate event_ids are silently skipped.
    Returns per-event success/failure.
    """
    accepted = []
    rejected = []

    conn = get_conn()
    try:
        for ev in batch.events:
            errors = []
            if not ev.store_id:
                errors.append("store_id is required")
            if not ev.event_type:
                errors.append("event_type is required")
            if not ev.timestamp:
                errors.append("timestamp is required")

            if errors:
                rejected.append({"event_id": ev.event_id, "errors": errors})
                continue

            row = _normalise(ev)
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO events
                        (event_id, store_id, camera_id, visitor_id, event_type,
                         timestamp, zone_id, dwell_ms, is_staff, confidence,
                         queue_depth, session_seq, raw_json)
                    VALUES
                        (:event_id, :store_id, :camera_id, :visitor_id, :event_type,
                         :timestamp, :zone_id, :dwell_ms, :is_staff, :confidence,
                         :queue_depth, :session_seq, :raw_json)
                """, row)
                accepted.append(ev.event_id)
            except Exception as e:
                rejected.append({"event_id": ev.event_id, "errors": [str(e)]})

        conn.commit()
    finally:
        conn.close()

    logger.info(
        f'"endpoint":"/events/ingest","accepted":{len(accepted)},"rejected":{len(rejected)}'
    )

    status = 200 if not rejected else 207
    return JSONResponse(
        status_code=status,
        content={
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejected_detail": rejected,
        },
    )
