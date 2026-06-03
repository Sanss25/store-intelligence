# CHOICES.md — Key Technical Decisions

## Decision 1: Detection Model — YOLOv8n + ByteTrack

### Options Considered
- **YOLOv8n** (nano): fast, runs on CPU, good person detection out of the box
- **YOLOv8s/m** (small/medium): higher accuracy but slower — unacceptable for real-time at 15fps on a laptop CPU
- **RT-DETR**: transformer-based, higher accuracy, but significantly heavier and harder to run without a GPU
- **MediaPipe Pose**: good for body keypoints but overkill for counting; no built-in tracking
- **GPT-4V / Gemini Vision**: considered for zone classification — see note below

### What AI Suggested
Claude and I discussed model selection. Claude flagged that for a 1080p 15fps stream on CPU, YOLOv8n is the practical choice — it runs at ~20-30fps on modern CPUs without GPU acceleration. It also noted that ByteTrack outperforms DeepSORT on occlusion cases (relevant for the billing queue clip) because ByteTrack uses IoU-based re-association rather than appearance features, making it faster and more robust when people are close together.

### What I Chose and Why
YOLOv8n + ByteTrack. The challenge explicitly states the clips are 15fps retail CCTV — throughput matters more than marginal accuracy gains. YOLOv8n runs fast enough to process clips in near-real-time and handles the entry/exit counting use case well. ByteTrack's low-confidence detection recovery is important for the partial occlusion edge case called out in the problem statement.

**On VLMs for zone classification**: I considered using Claude Vision or GPT-4V to classify which zone a person is in by describing their position in the frame. I decided against it for the core pipeline — API latency per frame would make real-time processing impossible, and the cost would be prohibitive for 20-minute clips. A rule-based approach (bounding box overlap with polygon zone definitions from `store_layout.json`) is faster, deterministic, and explainable. I would use a VLM for an offline QA pass — sampling frames and asking Claude Vision to verify zone assignments — but not in the hot path.

---

## Decision 2: Event Schema Design

### Options Considered
- **Match the sample_events.jsonl schema exactly**: the sample includes `gender_pred`, `age_pred`, `group_id` — fields our YOLOv8 pipeline doesn't produce without additional models
- **Match the challenge spec schema exactly**: `event_id`, `store_id`, `camera_id`, `visitor_id`, `event_type`, `timestamp`, `zone_id`, `dwell_ms`, `is_staff`, `confidence`, `metadata`
- **Hybrid**: emit the required schema fields, add optional demographic fields when available

### What AI Suggested
Claude noted the tension between the two schemas in the provided materials. The `sample_events.jsonl` appears to be from a more mature pipeline that includes a separate demographic inference model (face analysis for age/gender). The challenge spec schema is what the scoring harness will test against. Claude suggested building to the spec schema as the source of truth and treating demographic fields as optional extensions in the metadata block.

### What I Chose and Why
I built to the challenge spec schema (`app/models.py`) with the metadata block accepting optional extensions. This means the API and ingest validation are correct against the scoring harness. The detection pipeline doesn't emit `gender_pred` or `age_pred` because we're not running a face analysis model — face blur in the footage makes this unreliable anyway. If I had more time, I'd add an optional MediaPipe or DeepFace step for demographic inference on non-occluded frames.

The key schema decision I'm most confident in: **deriving timestamps from frame offset rather than wall clock time**. For pre-recorded clips, this is the only correct approach. Wall clock timestamps would make all events appear to happen at processing time, breaking any time-based analytics.

---

## Decision 3: API Storage — SQLite vs PostgreSQL

### Options Considered
- **SQLite (WAL mode)**: zero dependencies, single file, trivially containerised, sufficient for the challenge
- **PostgreSQL**: production-grade, concurrent writes, time-series queries via TimescaleDB
- **Redis + SQLite**: Redis for real-time occupancy counters, SQLite for event storage
- **In-memory (dict)**: fast but data lost on restart — unacceptable

### What AI Suggested
Claude's initial suggestion was PostgreSQL, citing production readiness. When I pushed back on complexity for a containerised challenge submission (PostgreSQL requires a second container, credentials, init scripts, health checks), Claude agreed SQLite in WAL mode is the right call: WAL mode supports concurrent readers with a single writer, the event volume for a 5-store challenge is well within SQLite's throughput, and it reduces the `docker-compose.yml` to a single service.

### What I Chose and Why
SQLite with WAL mode. The acceptance gate requires `docker compose up` with no manual steps — SQLite achieves this with a single container and a volume mount. I enabled WAL mode (`PRAGMA journal_mode=WAL`) so the Streamlit dashboard can read while the pipeline is writing without blocking.

**Where this breaks at scale**: At 40 live stores sending events concurrently, SQLite's single-writer lock becomes a bottleneck. The migration path is clear: swap `get_conn()` in `database.py` for a PostgreSQL connection pool (asyncpg or SQLAlchemy), add a second compose service, and update the indexed queries — the SQL itself doesn't change. I documented this in DESIGN.md rather than over-engineering for a challenge that runs on a laptop.
