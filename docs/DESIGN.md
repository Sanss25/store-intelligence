# Design

## Architecture

```
CCTV / video file
      │
      ▼
pipeline.py  (YOLOv8 detection + ByteTrack tracking)
      │  line-crossing → ENTRY/EXIT events
      ├──► events.jsonl        (local durable log, append-only)
      └──► POST /events/ingest (FastAPI, idempotent on event_id)
                    │
                    ▼
              SQLite (events table)
                    │
      ┌─────────────┼──────────────┬───────────────┐
      ▼             ▼              ▼               ▼
  /metrics      /funnel        /heatmap       /anomalies
      │             │              │               │
      └─────────────┴──────┬───────┴───────────────┘
                            ▼
                 dashboard.py (Streamlit, polls every 5s)
```

## Data flow

1. `pipeline.py` reads a video source frame by frame, runs YOLOv8
   person detection with ByteTrack for persistent track IDs, and
   watches for a track's center crossing a configurable vertical
   line (`--line-x`).
2. Each crossing emits a structured event (schema in
   `api/schemas.py`) — written to `events.jsonl` locally first
   (so nothing is lost if the API is down), then POSTed to the API.
3. The API stores events in SQLite keyed by `event_id`, so re-sent
   or retried events never double-count (`INSERT ... ON CONFLICT`
   pattern via a `PRIMARY KEY` + caught `IntegrityError`).
4. All read endpoints (`metrics`, `funnel`, `heatmap`, `anomalies`)
   are plain SQL aggregations over that one table — no separate
   pipeline needed to keep them in sync.
5. The dashboard polls the API on a fixed interval and re-renders.

## Event schema

One event type covers the whole customer journey (`ENTRY`, `EXIT`,
`ZONE_ENTER`, `ZONE_EXIT`, `QUEUE_JOIN`, `QUEUE_LEAVE`, `PURCHASE`).
The line-crossing pipeline in this repo only emits `ENTRY`/`EXIT` —
zone and queue events are the natural next producer to add (e.g. a
second camera model watching aisles), and the API/dashboard already
have first-class support for them so no schema change is needed.

## What's stubbed vs. real

- **Real, computed from data:** metrics, funnel drop-off, zone heat
  scores, and all four anomaly types are computed live from stored
  events — nothing is hardcoded.
- **Not yet wired into the pipeline:** `zone_id`, `dwell_ms`, and
  `queue_depth` are supported end-to-end by the schema/API/dashboard,
  but `pipeline.py` currently only tracks a single entry/exit line
  and always emits them as `null`/`0`. Populating them requires
  either a second detector for store zones/aisles or a queue-length
  heuristic — see "Next steps" in the README.
