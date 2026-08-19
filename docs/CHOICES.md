# Key choices

**YOLOv8n + ByteTrack.** Nano model for real-time CPU inference on a
single camera stream; ByteTrack gives persistent IDs across frames
without a re-ID model, which is enough for line-crossing counts.
Trade-off: nano is less accurate in crowded/occluded scenes than
larger YOLOv8 variants — fine for a single entry camera, would need
revisiting for a busy multi-camera store.

**SQLite, no ORM.** Single-file DB, zero setup, and the whole
project needs to run with `docker-compose up` and nothing else.
Event volume for a demo/single-store deployment is small enough that
raw SQL aggregation on every request is fast — no rollup tables or
caching layer needed yet. If this scaled to many stores/cameras,
the first change would be periodic materialized rollups (e.g. hourly
metrics tables) instead of aggregating the full event log per
request, plus swapping SQLite for Postgres for concurrent writes.

**Idempotent ingestion via `event_id` primary key.** The pipeline
writes locally to `events.jsonl` *before* calling the API, and the
API call can fail/retry/be re-run without risking double-counted
entries — `event_id` is a UUID generated once per detected
crossing, so a duplicate POST is a no-op.

**Local JSONL log as source of truth, API/DB as derived state.**
If the API or DB is ever wiped, `events.jsonl` is enough to
reconstruct it — a simple replay script (`POST` each line) would
fully rebuild the SQLite store.

**Streamlit dashboard, polling not push.** Simpler than websockets
for a project this size; a 5s poll is imperceptible for
occupancy/queue/anomaly monitoring and keeps the dashboard a plain
stateless client of the API.
