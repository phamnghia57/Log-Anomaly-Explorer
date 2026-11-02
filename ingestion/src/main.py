"""
Ingestion Service - Minh.

Nhan structured log tu demo-app, validate theo docs/architect/contracts/log-schema.json,
ghi vao OpenSearch (hoac quarantine neu sai schema).

Chay thu (tu thu muc ingestion/):
    pip install -r requirements.txt
    docker compose up -d            # OpenSearch local
    uvicorn src.main:app --reload --port 8000

Khong co OpenSearch? STORAGE_BACKEND=memory uvicorn src.main:app --port 8000
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Body, FastAPI, Query, Request, Header
from fastapi.responses import JSONResponse

from . import config
from .rate_limit import RateLimiter
from .retention import start_scheduler
from .storage import LogStore, StorageError, build_store
from .validator import validate_log

logger = logging.getLogger("ingestion")

store: LogStore = build_store()
ingest_limiter = RateLimiter(config.INGEST_RATE_LIMIT_RPS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        store.ensure_ready()
    except StorageError:
        # Khong chet luc khoi dong neu OpenSearch len cham; /health se bao degraded
        logger.exception("storage chua san sang luc khoi dong")
    stop = start_scheduler(store)
    yield
    if stop:
        stop.set()


app = FastAPI(title="Log Anomaly Explorer - Ingestion Service", lifespan=lifespan)


@app.middleware("http")
async def limit_ingestion_requests(request: Request, call_next):
    if request.method == "POST" and request.url.path in {"/ingest", "/ingest/batch"}:
        if not ingest_limiter.allow():
            return JSONResponse(status_code=429,
                                headers={"Retry-After": "1"},
                                content={"accepted": False, "reason": "rate_limit_exceeded"})
    return await call_next(request)


@app.exception_handler(StorageError)
async def _storage_error(_, exc: StorageError):
    logger.error("storage error: %s", exc)
    return JSONResponse(status_code=503, content={"accepted": False, "reason": "storage_unavailable"})


@app.get("/health")
def health():
    ok = store.ping()
    body = {"status": "ok" if ok else "degraded", "service": "ingestion",
            "storage": config.STORAGE_BACKEND}
    return JSONResponse(status_code=200 if ok else 503, content=body)


@app.post("/ingest", status_code=202)
def ingest(payload: dict = Body(...)):
    errors = validate_log(payload)
    if errors:
        store.write_quarantine(payload, errors)
        # api-contract.md: log sai schema -> 400, vao quarantine, khong vao index chinh
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "schema_validation_failed", "details": errors},
        )

    log_id = str(uuid.uuid4())
    store.write_log(log_id, payload)
    return {"accepted": True, "log_id": log_id}


@app.post("/ingest/batch", status_code=202)
def ingest_batch(payload: list[dict] = Body(...),
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """Validate the entire batch before writing any valid log. Index errors may be partial."""
    if not payload:
        return JSONResponse(status_code=400, content={"accepted": False, "reason": "empty_batch"})
    if len(payload) > config.MAX_BATCH_SIZE:
        return JSONResponse(status_code=413, content={"accepted": False, "reason": "batch_too_large",
                                                       "max_batch_size": config.MAX_BATCH_SIZE})
    invalid = [{"index": i, "details": errors} for i, log in enumerate(payload)
               if (errors := validate_log(log))]
    if invalid:
        for issue in invalid:
            store.write_quarantine(payload[issue["index"]], issue["details"])
        return JSONResponse(status_code=400, content={"accepted": False,
                             "reason": "schema_validation_failed", "invalid": invalid})
    # Stable document IDs let clients retry the same keyed batch after 503 without duplicates.
    # A client MUST use a new key for a different batch; unkeyed batches are not idempotent.
    if idempotency_key is not None and (not idempotency_key.strip() or len(idempotency_key) > 256):
        return JSONResponse(status_code=400, content={"accepted": False, "reason": "invalid_idempotency_key"})
    ids = [(str(uuid.uuid5(uuid.NAMESPACE_URL, f"ingest-batch:{idempotency_key}:{i}"))
            if idempotency_key else str(uuid.uuid4())) for i in range(len(payload))]
    store.write_logs(list(zip(ids, payload)))
    return {"accepted": True, "count": len(ids), "log_ids": ids}


def _parse_dt(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} phai la ISO 8601 date-time") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


@app.get("/search")
def search(
    service: str | None = None,
    trace_id: str | None = None,
    level: str | None = Query(None, pattern="^(DEBUG|INFO|WARN|ERROR|FATAL)$"),
    q: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    limit: int = Query(config.DEFAULT_SEARCH_LIMIT, ge=1, le=config.MAX_SEARCH_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Tim log theo field (khong phai semantic search). Mac dinh 24h gan nhat (theo api-contract.md).
    Expose tam thoi de Nghia test ngay; query-api that se goi thang vao storage."""
    try:
        time_from = _parse_dt(from_, "from")
        time_to = _parse_dt(to, "to")
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    if time_from is None and time_to is None:
        time_from = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    results, total, facets = store.search_with_facets(
        service=service, trace_id=trace_id, level=level, query=q,
        time_from=time_from, time_to=time_to, limit=limit, offset=offset,
    )
    return {"total": total, "results": results, "facets": facets}
