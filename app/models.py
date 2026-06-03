from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from datetime import datetime
import uuid


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = 1


class IngestEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str
    camera_id: Optional[str] = None
    visitor_id: Optional[str] = None
    event_type: str
    timestamp: str
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = 1.0
    metadata: Optional[EventMetadata] = None

    @field_validator("event_type")
    @classmethod
    def normalise_event_type(cls, v):
        return v.upper()

    @field_validator("timestamp")
    @classmethod
    def validate_ts(cls, v):
        # Accept both ISO formats
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                datetime.strptime(v[:26], fmt[:len(fmt)])
                return v
            except Exception:
                pass
        return v  # pass through; DB stores as text


class IngestBatch(BaseModel):
    events: list[IngestEvent] = Field(..., max_length=500)


class POSTransaction(BaseModel):
    transaction_id: str
    store_id: str
    timestamp: str
    basket_value_inr: float = 0.0
