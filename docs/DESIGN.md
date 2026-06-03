# DESIGN.md — Store Intelligence System

## Architecture Overview

The system is a four-stage pipeline: raw CCTV footage → detection layer → event stream → intelligence API → live dashboard.

```
CCTV Clips
    │
    ▼
pipeline/detect.py          ← YOLOv8n + ByteTrack
    │  (structured events)
    ▼
POST /events/ingest         ← FastAPI + SQLite (WAL mode)
    │
    ├── GET /stores/{id}/metrics
    ├── GET /stores/{id}/funnel
    ├── GET /stores/{id}/heatmap
    ├── GET /stores/{id}/anomalies
    └── GET /health
         │
         ▼
    Streamlit Dashboard      ← live polling
```

### Detection Layer

The detection pipeline (`pipeline/detect.py`) uses YOLOv8n with ByteTrack for multi-object tracking. A vertical counting line at a configurable X pixel coordinate determines entry/exit direction based on centroid movement across frames. A 30-frame debounce prevents duplicate events from the same track ID. REENTRY detection is handled by maintaining a `known_exits` set — any track ID that crosses the line inward after a recorded EXIT emits a REENTRY event instead of a second ENTRY.

Each detected person's bounding box centroid is tracked frame-to-frame. Direction is determined by whether the centroid crosses the counting line left-to-right (EXIT) or right-to-left (ENTRY). Model confidence scores are passed through directly into the event payload rather than being thresholded away.

### Event Stream

Events are emitted in the schema defined in `app/models.py` (Pydantic). Each event includes: `event_id` (UUID v4), `store_id`, `camera_id`, `visitor_id` (per-session token), `event_type`, ISO-8601 UTC timestamp derived from frame offset, and a metadata block. Events are written locally to `events.jsonl` and simultaneously POSTed to the API.

The timestamp is derived from clip frame number and FPS rather than wall clock time, which gives accurate relative timing for a pre-recorded clip.

### Intelligence API

Built with FastAPI and SQLite (WAL mode for concurrent reads). All five endpoints are implemented:

- `/events/ingest` — idempotent by `event_id` (INSERT OR IGNORE), validates required fields, returns per-event success/failure
- `/stores/{id}/metrics` — unique visitors, occupancy, conversion rate, avg dwell per zone, queue depth, abandonment rate; all excluding `is_staff=true`
- `/stores/{id}/funnel` — four-stage conversion funnel, deduplicated by `visitor_id`
- `/stores/{id}/heatmap` — zone frequency + dwell normalised 0–100, with `data_confidence` flag
- `/stores/{id}/anomalies` — queue spike, dead zone, conversion drop, stale feed
- `/health` — per-store last event timestamp with STALE_FEED warning if >10 min lag

### Storage

SQLite with WAL journal mode. Chosen for simplicity and zero-dependency deployment. The `events` table is indexed on `store_id`, `event_type`, `timestamp`, and `visitor_id` — the four dimensions every query uses. For a production 40-store deployment, the natural migration path is PostgreSQL with TimescaleDB for time-series partitioning.

### Containerisation

Single `docker-compose.yml` spins up the API. The SQLite file is persisted via a named Docker volume (`db_data`). No additional services required.

---

## AI-Assisted Decisions

### 1. Event deduplication strategy

I asked Claude: *"What's the right deduplication approach for an event ingest API where the detection pipeline might retry on network failure?"* Claude suggested `INSERT OR IGNORE` on `event_id` as the primary key rather than a separate deduplication table or a check-then-insert pattern. I agreed — it's atomic, avoids race conditions, and SQLite handles it efficiently. I did override one thing: Claude initially suggested returning a 409 on duplicates, but for an ingest pipeline that might retry in bulk, silently ignoring duplicates and returning `accepted` count is more operationally sound. I kept the 207 partial-success status for batches with validation errors.

### 2. Timestamp derivation from frame offset

Claude suggested using `datetime.now()` for event timestamps. I overrode this: for pre-recorded clips, wall clock time is wrong — it would make all events appear to have happened at processing time. Deriving timestamps from `frame_number / fps + clip_start_time` gives accurate relative timing. Claude agreed when I explained the use case, and suggested storing FPS from `cap.get(cv2.CAP_PROP_FPS)` rather than hardcoding it.

### 3. Funnel session deduplication

For the funnel endpoint, I asked Claude how to count "unique visitors who reached billing" without double-counting re-entries. Claude suggested `COUNT(DISTINCT visitor_id)` per stage, which correctly handles the case where a visitor generates multiple events of the same type. I validated this against the sample events file and confirmed it produces correct results for the re-entry edge case.
