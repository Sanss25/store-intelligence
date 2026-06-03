# Store Intelligence — Purplle Tech Challenge PS3

Real-time store analytics pipeline: CCTV → Detection → Events → API → Dashboard.

## Quick Start (5 commands)

```bash
# 1. Clone and enter the repo
git clone <your-repo-url> store-intelligence && cd store-intelligence

# 2. Start the API
docker compose up -d

# 3. Install pipeline dependencies (runs locally, not in Docker)
pip install ultralytics opencv-python requests

# 4. Run detection pipeline against your clips
./pipeline/run.sh "/path/to/Store 1" STORE_1

# 5. Open the dashboard
streamlit run dashboard.py
```

The API is now live at `http://localhost:8000`.

---

## Project Structure

```
store-intelligence/
├── pipeline/
│   ├── detect.py      # YOLOv8 + ByteTrack detection + event emission
│   └── run.sh         # Process all clips for a store
├── app/
│   ├── main.py        # FastAPI entrypoint + middleware
│   ├── database.py    # SQLite init + connection
│   ├── models.py      # Pydantic event schema
│   ├── ingestion.py   # POST /events/ingest (idempotent)
│   ├── metrics.py     # GET /stores/{id}/metrics
│   ├── funnel.py      # GET /stores/{id}/funnel
│   ├── heatmap.py     # GET /stores/{id}/heatmap
│   ├── anomalies.py   # GET /stores/{id}/anomalies
│   └── health.py      # GET /health
├── tests/
│   └── test_api.py    # pytest suite (>70% coverage)
├── docs/
│   ├── DESIGN.md
│   └── CHOICES.md
├── dashboard.py       # Streamlit live dashboard
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/events/ingest` | Ingest up to 500 events (idempotent) |
| GET  | `/stores/{id}/metrics` | Unique visitors, occupancy, conversion rate, dwell, queue |
| GET  | `/stores/{id}/funnel` | Entry → Zone → Billing → Purchase with dropoff % |
| GET  | `/stores/{id}/heatmap` | Zone heat scores normalised 0–100 |
| GET  | `/stores/{id}/anomalies` | Queue spike, dead zone, conversion drop, stale feed |
| GET  | `/health` | Service status + per-store last event timestamp |

### Example: Ingest events

```bash
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "store_id": "STORE_BLR_002",
      "camera_id": "CAM_ENTRY_01",
      "visitor_id": "VIS_c8a2f1",
      "event_type": "ENTRY",
      "timestamp": "2026-03-03T14:22:10Z",
      "zone_id": null,
      "dwell_ms": 0,
      "is_staff": false,
      "confidence": 0.91,
      "metadata": {"queue_depth": null, "session_seq": 1}
    }]
  }'
```

### Example: Get metrics

```bash
curl http://localhost:8000/stores/STORE_BLR_002/metrics
```

---

## Running Tests

```bash
pip install pytest httpx
pytest tests/ -v --tb=short
```

---

## Running the Detection Pipeline Manually

```bash
# Single clip
python pipeline/detect.py \
  --video "/path/to/CAM 3 - entry.mp4" \
  --store STORE_1 \
  --camera CAM3_ENTRY \
  --line_x 1180

# All clips for a store
./pipeline/run.sh "/path/to/Store 1" STORE_1
```

Arguments:
- `--video`: path to video file
- `--store`: store ID (e.g. `STORE_1`, `STORE_BLR_002`)
- `--camera`: camera ID (e.g. `CAM_ENTRY`, `CAM_ZONE`, `CAM_BILLING`)
- `--line_x`: pixel X coordinate of the counting line (default: 1180)
- `--no_display`: run headless (no OpenCV window)

Events are written to `events.jsonl` and POSTed to the API in real time.

---

## Architecture

See `docs/DESIGN.md` for full architecture overview and AI-assisted decision log.  
See `docs/CHOICES.md` for model selection, schema design, and storage rationale.

## Dashboard

The Streamlit dashboard (`dashboard.py`) polls the API every 5 seconds and shows live metrics for any store. Run with `streamlit run dashboard.py`.
