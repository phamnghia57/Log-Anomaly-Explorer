"""
Ingestion Service - Minh.

Nhan structured log tu demo-app, validate theo docs/contracts/log-schema.json,
ghi vao kho du lieu (hoac quarantine neu sai schema).

Chay thu:
    pip install -r ingestion/requirements.txt
    uvicorn ingestion.src.main:app --reload --port 8000
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI

from .storage import InMemoryLogStore, LogStore
from .validator import validate_log

app = FastAPI(title="Log Anomaly Explorer - Ingestion Service")

# TODO (Minh): thay InMemoryLogStore bang LogStore that (ES/OpenSearch/ClickHouse)
store: LogStore = InMemoryLogStore()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ingestion"}


@app.post("/ingest", status_code=202)
def ingest(payload: dict):
    errors = validate_log(payload)
    if errors:
        store.write_quarantine(payload, errors)
        return {"accepted": False, "reason": "schema_validation_failed", "details": errors}

    log_id = str(uuid.uuid4())
    store.write_log(log_id, payload)
    return {"accepted": True, "log_id": log_id}


@app.get("/search")
def search(service: str | None = None, trace_id: str | None = None, q: str | None = None):
    """Expose tam thoi de Nghia test ngay; query-api that se goi thang vao storage."""
    results = store.search(service=service, trace_id=trace_id, query=q)
    return {"total": len(results), "results": results}
