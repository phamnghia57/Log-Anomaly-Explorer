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
import time
import uuid
from collections import deque
from threading import Lock
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from . import config
from .retention import start_scheduler
from .storage import LogStore, StorageError, build_store
from .validator import validate_log

logger = logging.getLogger("ingestion")

store: LogStore = build_store()


class SlidingWindowRateLimiter:
    """Gioi han RPS dung chung cac ingest routes, an toan giua threads (1 process)."""

    def __init__(self, limit: int):
        self.limit = limit
        self._times: deque[float] = deque()
        self._lock = Lock()

    def check(self) -> None:
        now = time.monotonic()
        with self._lock:
            while self._times and self._times[0] <= now - 1.0:
                self._times.popleft()
            if len(self._times) >= self.limit:
                raise HTTPException(status_code=429, detail="rate_limit_exceeded",
                                    headers={"Retry-After": "1"})
            self._times.append(now)


limiter = SlidingWindowRateLimiter(config.INGEST_RATE_LIMIT_RPS)


def allow_ingest_request() -> None:
    limiter.check()


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


@app.post("/ingest", status_code=202, dependencies=[Depends(allow_ingest_request)])
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


@app.post("/ingest/batch", status_code=202, dependencies=[Depends(allow_ingest_request)])
def ingest_batch(payload: list[dict] = Body(...)):
    """Batch la JSON array; validate TOAN BO truoc khi ghi, invalid -> quarantine.

    Loi storage sau khi ghi co the la partial write (OpenSearch Bulk API),
    client can retry co kiem soat. Khong trung endpoint /ingest/bulk cua nhanh ca nhan.
    """
    if not payload or len(payload) > config.INGEST_MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"batch must contain 1..{config.INGEST_MAX_BATCH_SIZE} logs")
    invalid = [{"index": i, "details": errors} for i, item in enumerate(payload)
               if (errors := validate_log(item))]
    if invalid:
        for entry in invalid:
            store.write_quarantine(payload[entry["index"]], entry["details"])
        return JSONResponse(status_code=400, content={
            "accepted": False, "reason": "schema_validation_failed", "errors": invalid,
        })
    items = [(str(uuid.uuid4()), log) for log in payload]
    store.write_logs_batch(items)
    return {"accepted": True, "accepted_count": len(items),
            "log_ids": [log_id for log_id, _ in items]}


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

    results, total = store.search_with_total(
        service=service, trace_id=trace_id, level=level, query=q,
        time_from=time_from, time_to=time_to, limit=limit, offset=offset,
    )
    return {"total": total, "results": results}


@app.get("/search/aggregations")
def search_aggregations(
    service: str | None = None,
    trace_id: str | None = None,
    level: str | None = Query(None, pattern="^(DEBUG|INFO|WARN|ERROR|FATAL)$"),
    q: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    interval: str = Query("hour", pattern="^(hour|day)$"),
):
    try:
        time_from = _parse_dt(from_, "from")
        time_to = _parse_dt(to, "to")
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    if time_from is None and time_to is None:
        time_from = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return store.aggregate_logs(service=service, level=level, trace_id=trace_id, query=q,
                                time_from=time_from, time_to=time_to, interval=interval)
