# Store Intelligence

Real-time store analytics from CCTV footage: detection → tracking →
events → API → live dashboard.

CCTV video → **YOLOv8 + ByteTrack** detects and tracks people →
line-crossing events stream into a **FastAPI + SQLite** backend →
a **Streamlit** dashboard shows live occupancy, conversion funnel,
zone heatmap, and anomaly alerts.

## Quickstart

```bash
git clone <this repo>
cd store-intelligence
pip install -r requirements.txt

# 1. Start the API
uvicorn api.main:app --reload --port 8000

# 2. Start the dashboard (new terminal)
streamlit run dashboard.py

# 3. Run the detection pipeline against a video file (new terminal)
python pipeline.py --video path/to/video.mp4 --store STORE_1 --camera CAM3_ENTRY
```

Or with Docker (API + dashboard; pipeline runs on the host since it
needs camera/video access):

```bash
docker compose up --build
python pipeline.py --video path/to/video.mp4 --api-url http://localhost:8000
```

Dashboard: http://localhost:8501 · API docs: http://localhost:8000/docs

## Project layout

```
pipeline.py           # detection + tracking + event emission
api/
  main.py             # FastAPI routes
  db.py               # SQLite persistence, idempotent ingestion
  analytics.py         # metrics / funnel / heatmap / anomaly queries
  schemas.py           # Pydantic request/response models
dashboard.py           # Streamlit live dashboard
tests/test_api.py      # pytest suite for the API
docs/DESIGN.md          # architecture + data flow
docs/CHOICES.md         # rationale for key technical decisions
docker-compose.yml
```

## API

| Endpoint | Description |
|---|---|
| `GET /health` | DB connectivity + total events ingested |
| `POST /events/ingest` | Idempotent event ingestion (by `event_id`) |
| `GET /stores/{id}/metrics` | Visitors, occupancy, entries/exits, conversion, dwell, queue |
| `GET /stores/{id}/funnel` | Entry → zone → queue → purchase, with drop-off % |
| `GET /stores/{id}/heatmap` | Per-zone visit counts and 0–100 heat score |
| `GET /stores/{id}/anomalies` | Queue spikes, dead zones, conversion drops, stale feeds |

## Tests

```bash
pytest tests/ -v
```

## Status / next steps

The pipeline currently tracks a single entry/exit line and emits
`ENTRY`/`EXIT` events; the API and dashboard already fully support
`zone_id`, `dwell_ms`, and `queue_depth` for funnel/heatmap/anomaly
features, but nothing populates them yet. Next: a second
zone-detection pass (or a lightweight per-zone counting line) to
light up the heatmap and full funnel with real data. See
`docs/DESIGN.md` for the honest breakdown of what's real vs. stubbed.
