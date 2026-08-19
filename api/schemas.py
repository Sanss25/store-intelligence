"""Pydantic schemas for the Store Intelligence API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "QUEUE_JOIN", "QUEUE_LEAVE", "PURCHASE"
]


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    session_seq: Optional[int] = 1


class EventIngest(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: EventType
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: Optional[int] = 0
    is_staff: Optional[bool] = False
    confidence: Optional[float] = Field(default=0.9, ge=0.0, le=1.0)
    metadata: Optional[EventMetadata] = None


class IngestResponse(BaseModel):
    event_id: str
    status: Literal["created", "duplicate"]


class StoreMetrics(BaseModel):
    store_id: str
    unique_visitors: int
    occupancy: int
    entries: int
    exits: int
    purchases: int
    conversion_rate: float
    avg_dwell_ms: float
    current_queue_depth: int
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


class FunnelStage(BaseModel):
    stage: str
    visitors: int
    dropoff_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage]


class ZoneHeat(BaseModel):
    zone_id: str
    visits: int
    avg_dwell_ms: float
    heat_score: float  # 0-100


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[ZoneHeat]


class Anomaly(BaseModel):
    type: Literal["QUEUE_SPIKE", "DEAD_ZONE", "CONVERSION_DROP", "STALE_FEED"]
    severity: Literal["low", "medium", "high"]
    message: str
    detected_at: datetime


class AnomalyResponse(BaseModel):
    store_id: str
    anomalies: list[Anomaly]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db_connected: bool
    total_events: int
    server_time: datetime
