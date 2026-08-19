"""Store Intelligence API.

Run locally:
    uvicorn api.main:app --reload --port 8000

Endpoints:
    GET  /health
    POST /events/ingest
    GET  /stores/{store_id}/metrics
    GET  /stores/{store_id}/funnel
    GET  /stores/{store_id}/heatmap
    GET  /stores/{store_id}/anomalies
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from . import analytics, db
from .schemas import (
    AnomalyResponse,
    EventIngest,
    FunnelResponse,
    HealthResponse,
    HeatmapResponse,
    IngestResponse,
    StoreMetrics,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Store Intelligence API", version="1.0.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        with db.get_conn() as conn:
            total = db.count_events(conn)
        return HealthResponse(
            status="ok",
            db_connected=True,
            total_events=total,
            server_time=datetime.now(timezone.utc),
        )
    except Exception:
        return HealthResponse(
            status="degraded",
            db_connected=False,
            total_events=0,
            server_time=datetime.now(timezone.utc),
        )


@app.post("/events/ingest", response_model=IngestResponse)
def ingest_event(event: EventIngest) -> IngestResponse:
    payload = event.model_dump(mode="json")
    with db.get_conn() as conn:
        created = db.insert_event(conn, payload)
    return IngestResponse(event_id=event.event_id, status="created" if created else "duplicate")


@app.get("/stores/{store_id}/metrics", response_model=StoreMetrics)
def store_metrics(store_id: str) -> StoreMetrics:
    with db.get_conn() as conn:
        data = analytics.get_metrics(conn, store_id)
    return StoreMetrics(**data)


@app.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
def store_funnel(store_id: str) -> FunnelResponse:
    with db.get_conn() as conn:
        data = analytics.get_funnel(conn, store_id)
    return FunnelResponse(**data)


@app.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
def store_heatmap(store_id: str) -> HeatmapResponse:
    with db.get_conn() as conn:
        data = analytics.get_heatmap(conn, store_id)
    return HeatmapResponse(**data)


@app.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
def store_anomalies(store_id: str) -> AnomalyResponse:
    with db.get_conn() as conn:
        data = analytics.get_anomalies(conn, store_id)
    return AnomalyResponse(**data)
