# PROMPT: "Write pytest tests for a FastAPI store analytics API. Cover:
#   1. POST /events/ingest - happy path, idempotency, malformed events, batch >500
#   2. GET /stores/{id}/metrics - basic metrics, staff exclusion, zero-purchase store
#   3. GET /stores/{id}/funnel - conversion funnel accuracy, re-entry deduplication
#   4. GET /stores/{id}/anomalies - queue spike, dead zone, stale feed
#   5. GET /health - STALE_FEED warning
#   Edge cases: empty store, all-staff clip, zero purchases, re-entry in funnel"
# CHANGES MADE: Added real DB setup/teardown via tmp sqlite file.
#   Removed mocking (tests hit real endpoints).
#   Added store STORE_BLR_002 to match the acceptance gate requirement.
#   Fixed timestamp format to match our validator.

import os
import uuid
import pytest
import sqlite3
import tempfile
from datetime import datetime, UTC, timedelta
from fastapi.testclient import TestClient

# Point DB to a temp file before importing app
tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DB_PATH"] = tmp_db.name

from app.main import app
from app.database import init_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db():
    """Reset DB before each test."""
    init_db()
    conn = sqlite3.connect(tmp_db.name)
    conn.executescript("DELETE FROM events; DELETE FROM pos_transactions;")
    conn.commit()
    conn.close()
    yield


def ts(offset_sec=0):
    return (datetime.now(UTC) + timedelta(seconds=offset_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(**kwargs):
    defaults = {
        "event_id":   str(uuid.uuid4()),
        "store_id":   "STORE_BLR_002",
        "camera_id":  "CAM_ENTRY_01",
        "visitor_id": f"VIS_{uuid.uuid4().hex[:6]}",
        "event_type": "ENTRY",
        "timestamp":  ts(),
        "zone_id":    None,
        "dwell_ms":   0,
        "is_staff":   False,
        "confidence": 0.91,
        "metadata":   {"queue_depth": None, "session_seq": 1},
    }
    defaults.update(kwargs)
    return defaults


# ════════════════════════════════════════════════════════
# Part 1 — Ingest
# ════════════════════════════════════════════════════════

class TestIngest:

    def test_happy_path(self):
        ev = make_event()
        r = client.post("/events/ingest", json={"events": [ev]})
        assert r.status_code == 200
        assert r.json()["accepted"] == 1
        assert r.json()["rejected"] == 0

    def test_idempotency(self):
        """Same event ingested twice → accepted=1 both times, no duplicate."""
        ev = make_event()
        r1 = client.post("/events/ingest", json={"events": [ev]})
        r2 = client.post("/events/ingest", json={"events": [ev]})
        assert r1.json()["accepted"] == 1
        assert r2.json()["accepted"] == 1  # IGNORE, not error

        # Metrics should still show 1 visitor not 2
        metrics = client.get("/stores/STORE_BLR_002/metrics").json()
        assert metrics["entries"] == 1

    def test_partial_success_malformed(self):
        # Missing store_id and event_type — Pydantic rejects whole batch at request level (422)
        bad_batch = {"events": [{"event_id": str(uuid.uuid4())}]}
        r = client.post("/events/ingest", json=bad_batch)
        assert r.status_code == 422

    def test_partial_success_mixed_valid(self):
        # Both events structurally valid but one has empty store_id — our logic rejects it
        good = make_event()
        bad  = make_event(store_id="", event_type="ENTRY")
        r = client.post("/events/ingest", json={"events": [good, bad]})
        assert r.status_code in (200, 207)
        body = r.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1

    def test_batch_limit(self):
        events = [make_event() for _ in range(501)]
        r = client.post("/events/ingest", json={"events": events})
        assert r.status_code == 422  # Pydantic rejects >500

    def test_staff_flagged(self):
        ev = make_event(is_staff=True)
        client.post("/events/ingest", json={"events": [ev]})
        metrics = client.get("/stores/STORE_BLR_002/metrics").json()
        assert metrics["unique_visitors"] == 0  # staff excluded


# ════════════════════════════════════════════════════════
# Part 2 — Metrics
# ════════════════════════════════════════════════════════

class TestMetrics:

    def test_empty_store(self):
        r = client.get("/stores/STORE_EMPTY/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["unique_visitors"] == 0
        assert body["occupancy"] == 0
        assert body["conversion_rate"] == 0.0

    def test_basic_entry_exit(self):
        vis = f"VIS_{uuid.uuid4().hex[:6]}"
        client.post("/events/ingest", json={"events": [
            make_event(visitor_id=vis, event_type="ENTRY"),
            make_event(visitor_id=vis, event_type="EXIT"),
        ]})
        m = client.get("/stores/STORE_BLR_002/metrics").json()
        assert m["entries"] == 1
        assert m["exits"] == 1
        assert m["occupancy"] == 0

    def test_all_staff_clip(self):
        """If all events are staff, customer metrics should be zero."""
        for _ in range(5):
            client.post("/events/ingest", json={"events": [
                make_event(is_staff=True, event_type="ENTRY")
            ]})
        m = client.get("/stores/STORE_BLR_002/metrics").json()
        assert m["unique_visitors"] == 0
        assert m["occupancy"] == 0

    def test_zero_purchases(self):
        client.post("/events/ingest", json={"events": [make_event()]})
        m = client.get("/stores/STORE_BLR_002/metrics").json()
        assert m["conversion_rate"] == 0.0  # no billing events


# ════════════════════════════════════════════════════════
# Part 3 — Funnel
# ════════════════════════════════════════════════════════

class TestFunnel:

    def test_basic_funnel(self):
        vis = f"VIS_{uuid.uuid4().hex[:6]}"
        client.post("/events/ingest", json={"events": [
            make_event(visitor_id=vis, event_type="ENTRY"),
            make_event(visitor_id=vis, event_type="ZONE_ENTER", zone_id="SKINCARE"),
            make_event(visitor_id=vis, event_type="BILLING_QUEUE_JOIN",
                       metadata={"queue_depth": 1, "session_seq": 3}),
        ]})
        f = client.get("/stores/STORE_BLR_002/funnel").json()
        stages = {s["stage"]: s for s in f["stages"]}
        assert stages["entry"]["count"] == 1
        assert stages["zone_visit"]["count"] == 1
        assert stages["billing_queue"]["count"] == 1

    def test_reentry_not_double_counted(self):
        """Same visitor_id entering twice should count as 1 in funnel."""
        vis = "VIS_RETEST"
        client.post("/events/ingest", json={"events": [
            make_event(visitor_id=vis, event_type="ENTRY"),
            make_event(visitor_id=vis, event_type="EXIT"),
            make_event(visitor_id=vis, event_type="ENTRY"),  # re-entry
        ]})
        f = client.get("/stores/STORE_BLR_002/funnel").json()
        entry_stage = next(s for s in f["stages"] if s["stage"] == "entry")
        assert entry_stage["count"] == 1  # deduplicated by visitor_id


# ════════════════════════════════════════════════════════
# Part 4 — Anomalies
# ════════════════════════════════════════════════════════

class TestAnomalies:

    def test_queue_spike_warn(self):
        client.post("/events/ingest", json={"events": [
            make_event(event_type="BILLING_QUEUE_JOIN",
                       metadata={"queue_depth": 6, "session_seq": 1})
        ]})
        a = client.get("/stores/STORE_BLR_002/anomalies").json()
        types = [x["anomaly_type"] for x in a["anomalies"]]
        assert "BILLING_QUEUE_SPIKE" in types

    def test_no_anomalies_empty_store(self):
        a = client.get("/stores/STORE_EMPTY_A/anomalies").json()
        assert a["anomaly_count"] == 0

    def test_stale_feed_detected(self):
        # Insert an event with a very old timestamp
        old_ts = (datetime.now(UTC) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        client.post("/events/ingest", json={"events": [
            make_event(timestamp=old_ts)
        ]})
        a = client.get("/stores/STORE_BLR_002/anomalies").json()
        types = [x["anomaly_type"] for x in a["anomalies"]]
        assert "STALE_FEED" in types


# ════════════════════════════════════════════════════════
# Part 5 — Health
# ════════════════════════════════════════════════════════

class TestHealth:

    def test_health_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "OK"

    def test_health_shows_store(self):
        client.post("/events/ingest", json={"events": [make_event()]})
        r = client.get("/health").json()
        assert "STORE_BLR_002" in r["stores"]

    def test_stale_feed_in_health(self):
        old_ts = (datetime.now(UTC) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        client.post("/events/ingest", json={"events": [make_event(timestamp=old_ts)]})
        h = client.get("/health").json()
        store_status = h["stores"]["STORE_BLR_002"]["status"]
        assert store_status == "STALE_FEED"
