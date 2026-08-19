"""Tests for the Store Intelligence API.

Uses a temp SQLite file per test session and FastAPI's TestClient
so no server / network needed to run these.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["STORE_INTEL_DB"] = path

    # import after env var is set so db.py picks up the temp path
    from api import db, main

    db.DB_PATH = path
    db.init_db(path)

    with TestClient(main.app) as c:
        yield c

    os.remove(path)


def make_event(event_id="evt-1", store_id="STORE_TEST", event_type="ENTRY", visitor="VIS_1", **overrides):
    event = {
        "event_id": event_id,
        "store_id": store_id,
        "camera_id": "CAM1",
        "visitor_id": visitor,
        "event_type": event_type,
        "timestamp": "2026-06-03T19:57:07.477891+00:00",
        "zone_id": overrides.get("zone_id"),
        "dwell_ms": overrides.get("dwell_ms", 0),
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": overrides.get("queue_depth"), "session_seq": 1},
    }
    return event


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ingest_creates_event(client):
    resp = client.post("/events/ingest", json=make_event())
    assert resp.status_code == 200
    assert resp.json()["status"] == "created"


def test_ingest_is_idempotent(client):
    event = make_event(event_id="evt-dup")
    first = client.post("/events/ingest", json=event)
    second = client.post("/events/ingest", json=event)
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "duplicate"


def test_ingest_rejects_invalid_event_type(client):
    event = make_event()
    event["event_type"] = "NOT_A_REAL_TYPE"
    resp = client.post("/events/ingest", json=event)
    assert resp.status_code == 422


def test_metrics_reflect_entries_and_exits(client):
    client.post("/events/ingest", json=make_event(event_id="e1", event_type="ENTRY", visitor="VIS_1"))
    client.post("/events/ingest", json=make_event(event_id="e2", event_type="ENTRY", visitor="VIS_2"))
    client.post("/events/ingest", json=make_event(event_id="e3", event_type="EXIT", visitor="VIS_1"))

    resp = client.get("/stores/STORE_TEST/metrics")
    body = resp.json()
    assert body["entries"] == 2
    assert body["exits"] == 1
    assert body["occupancy"] == 1
    assert body["unique_visitors"] == 2


def test_metrics_empty_store_returns_zeros(client):
    resp = client.get("/stores/STORE_EMPTY/metrics")
    body = resp.json()
    assert body["entries"] == 0
    assert body["occupancy"] == 0
    assert body["conversion_rate"] == 0.0


def test_funnel_dropoff(client):
    client.post("/events/ingest", json=make_event(event_id="f1", event_type="ENTRY", visitor="VIS_1"))
    client.post("/events/ingest", json=make_event(event_id="f2", event_type="ENTRY", visitor="VIS_2"))
    client.post("/events/ingest", json=make_event(event_id="f3", event_type="PURCHASE", visitor="VIS_1"))

    resp = client.get("/stores/STORE_TEST/funnel")
    stages = {s["stage"]: s for s in resp.json()["stages"]}
    assert stages["Entry"]["visitors"] == 2
    assert stages["Purchase"]["visitors"] == 1
    assert stages["Purchase"]["dropoff_pct"] == 50.0


def test_heatmap_zones(client):
    client.post("/events/ingest", json=make_event(event_id="h1", event_type="ZONE_ENTER", visitor="VIS_1", zone_id="AISLE_1"))
    client.post("/events/ingest", json=make_event(event_id="h2", event_type="ZONE_ENTER", visitor="VIS_2", zone_id="AISLE_1"))
    client.post("/events/ingest", json=make_event(event_id="h3", event_type="ZONE_ENTER", visitor="VIS_3", zone_id="AISLE_2"))

    resp = client.get("/stores/STORE_TEST/heatmap")
    zones = {z["zone_id"]: z for z in resp.json()["zones"]}
    assert zones["AISLE_1"]["visits"] == 2
    assert zones["AISLE_1"]["heat_score"] == 100.0
    assert zones["AISLE_2"]["heat_score"] == 50.0


def test_queue_spike_anomaly(client):
    client.post("/events/ingest", json=make_event(event_id="q1", event_type="QUEUE_JOIN", visitor="VIS_1", queue_depth=8))
    resp = client.get("/stores/STORE_TEST/anomalies")
    types = [a["type"] for a in resp.json()["anomalies"]]
    assert "QUEUE_SPIKE" in types


def test_anomalies_empty_store(client):
    resp = client.get("/stores/STORE_NOTHING/anomalies")
    assert resp.status_code == 200
    assert resp.json()["anomalies"] == [] or all(
        a["type"] != "QUEUE_SPIKE" for a in resp.json()["anomalies"]
    )
