import time
import uuid
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, UTC

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.database import init_db
from app.ingestion import router as ingest_router
from app.metrics import router as metrics_router
from app.funnel import router as funnel_router
from app.heatmap import router as heatmap_router
from app.anomalies import router as anomalies_router
from app.health import router as health_router

# ── Structured logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}',
)
logger = logging.getLogger("store_intelligence")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info('"DB initialised"')
    yield


app = FastAPI(title="Store Intelligence API", version="1.0.0", lifespan=lifespan)


# ── Request logging middleware ───────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    store_id = request.path_params.get("store_id", "-")
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            f'"trace_id":"{trace_id}","endpoint":"{request.url.path}",'
            f'"error":"{exc}"'
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "trace_id": trace_id},
        )
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    logger.info(
        f'"trace_id":"{trace_id}","store_id":"{store_id}",'
        f'"endpoint":"{request.url.path}","method":"{request.method}",'
        f'"status_code":{response.status_code},"latency_ms":{latency_ms}'
    )
    response.headers["X-Trace-Id"] = trace_id
    return response


app.include_router(ingest_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(heatmap_router)
app.include_router(anomalies_router)
app.include_router(health_router)
