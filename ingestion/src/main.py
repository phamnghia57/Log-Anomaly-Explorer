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

from fastapi import Body, FastAPI, Query
from fastapi.responses import JSONResponse

from . import config
from .retention import start_scheduler
from .storage import LogStore, StorageError, build_store
from .validator import validate_log

logger = logging.getLogger("ingestion")

store: LogStore = build_store()


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


# VT-016: import hang loat. Gioi han batch de bao ve p95 (xem README.md "Test strategy" / NFR2).
MAX_BULK_BATCH_SIZE = 500


@app.post("/ingest/bulk", status_code=207)
def ingest_bulk(payload: dict = Body(...)):
    """Nhan nhieu structured log trong 1 request (xem api-contract.md muc "POST /ingest/bulk").

    INVARIANT quan trong nhat (bat buoc giu khi sua code nay sau nay): mot ban ghi loi
    (sai schema HOAC ghi/persist that bai) khong duoc lam mat cac ban ghi hop le khac trong
    cung batch, va KHONG BAO GIO duoc bao accepted=true cho mot ban ghi ma persistence that bai
    thuc su. Vi du doc verify dieu nay: ingestion/tests/test_bulk_ingest.py
    ::test_bulk_persistence_failure_never_reported_as_accepted.
    """
    logs = payload.get("logs")
    if not isinstance(logs, list) or len(logs) == 0:
        return JSONResponse(status_code=400, content={"accepted": False, "reason": "empty_batch"})
    if len(logs) > MAX_BULK_BATCH_SIZE:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "batch_too_large", "max_batch_size": MAX_BULK_BATCH_SIZE},
        )

    results: list[dict] = []
    accepted = quarantined = failed = 0
    for index, log in enumerate(logs):
        errors = validate_log(log) if isinstance(log, dict) else ["<root>: phai la object"]
        if errors:
            store.write_quarantine(log, errors)
            results.append({"index": index, "status": "quarantined",
                             "reason": "schema_validation_failed", "details": errors})
            quarantined += 1
            continue

        log_id = str(uuid.uuid4())
        try:
            store.write_log(log_id, log)
        except StorageError:
            # KHONG duoc chuyen thanh "accepted" du da sinh log_id - day la invariant
            # trung tam cua change request VT-016 (xem docstring ham nay).
            results.append({"index": index, "status": "failed", "reason": "storage_unavailable"})
            failed += 1
            continue

        results.append({"index": index, "status": "accepted", "log_id": log_id})
        accepted += 1

    return JSONResponse(
        status_code=207,
        content={"accepted": accepted, "quarantined": quarantined, "failed": failed, "results": results},
    )


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
        service=service, trace_id=trace_id, query=q,
        time_from=time_from, time_to=time_to, limit=limit, offset=offset,
    )
    return {"total": total, "results": results}
