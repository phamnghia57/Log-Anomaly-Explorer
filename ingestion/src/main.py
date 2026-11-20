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
from collections import deque
from threading import Lock
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from . import config
from .idempotency import IdempotencyStore
from .ingest_core import Result, handle_ingest, handle_ingest_batch
from .retention import start_scheduler
from .storage import LogStore, StorageError, build_store

logger = logging.getLogger("ingestion")

store: LogStore = build_store()
# VT-014: cache idempotency trong process (xem src/idempotency.py ve gioi han nhieu replica)
idempotency = IdempotencyStore(config.IDEMPOTENCY_TTL_SECONDS)


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
def ingest(payload: dict = Body(...),
           idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    return _to_response(handle_ingest(store, idempotency, payload, idempotency_key))


@app.post("/ingest/batch", status_code=202, dependencies=[Depends(allow_ingest_request)])
def ingest_batch(payload: list[dict] = Body(...),
                 idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    """Batch la JSON array; validate TOAN BO truoc khi ghi, invalid -> quarantine.

    Loi storage sau khi ghi co the la partial write (OpenSearch Bulk API),
    client can retry co kiem soat. Khong trung endpoint /ingest/bulk cua nhanh ca nhan.
    """
    return _to_response(handle_ingest_batch(store, idempotency, payload, idempotency_key,
                                            config.INGEST_MAX_BATCH_SIZE))


def _to_response(result: Result) -> JSONResponse:
    """Map Result (doc lap framework) -> HTTP response, giu nguyen status/body cu."""
    return JSONResponse(status_code=result.status, content=result.body,
                        headers=result.headers or None)


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
