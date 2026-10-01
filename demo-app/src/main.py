"""
Demo App - nguon log cho Log Anomaly Explorer.

Phu trach: Manh.
Trach nhiem: sinh structured log + trace (qua OpenTelemetry), va cung cap co che
fault injection co chu dich de tao du lieu cho labeled incidents (Nam).

Chay thu:
    pip install -r demo-app/requirements.txt
    uvicorn demo-app.src.main:app --reload --port 8001
"""

from __future__ import annotations

import os
import random
import traceback
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException

from .telemetry import get_current_trace_context, setup_telemetry

SERVICE_NAME = "demo-web"
INGESTION_URL = os.environ.get("INGESTION_URL", "http://localhost:8000/ingest")

app = FastAPI(title="Log Anomaly Explorer - Demo App")

# TODO (Manh): bo comment khi da cau hinh xong OpenTelemetry SDK that
# setup_telemetry(SERVICE_NAME)


def emit_log(level: str, message: str, stack_trace: str | None = None) -> None:
    """Sinh mot structured log dung theo docs/contracts/log-schema.json va gui ve Ingestion.

    TODO (Manh): thay trace_id/span_id gia bang get_current_trace_context() that.
    """
    try:
        trace_ctx = get_current_trace_context()
    except NotImplementedError:
        # Placeholder cho den khi OpenTelemetry duoc cau hinh that.
        trace_ctx = {"trace_id": "TODO-trace-id", "span_id": "TODO-span-id"}

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": SERVICE_NAME,
        "trace_id": trace_ctx["trace_id"],
        "span_id": trace_ctx["span_id"],
        "message": message,
        "stack_trace": stack_trace,
    }
    try:
        httpx.post(INGESTION_URL, json=payload, timeout=2.0)
    except httpx.HTTPError:
        # Khong de loi gui log lam sap ung dung demo.
        pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/api/items")
def list_items() -> dict:
    """Endpoint happy-path binh thuong, dung de tao log nen (baseline)."""
    emit_log("INFO", "Listed items successfully")
    return {"items": ["item-1", "item-2", "item-3"]}


@app.get("/simulate-error")
def simulate_error(rate: float = 0.3) -> dict:
    """Fault injection co chu dich.

    Goi endpoint nay lap lai (vd. bang load-tests/locustfile.py) voi `rate` khac nhau
    de tao ra cac giai doan bat thuong co kiem soat, phuc vu:
      - GitHub evidence "fault injection"
      - Du lieu dau vao cho "labeled incidents" (Nam tu gan nhan
        giai doan nay la mot incident that trong qua trinh danh gia precision/recall)
    """
    if random.random() < rate:
        try:
            raise RuntimeError("Simulated downstream failure")
        except RuntimeError:
            emit_log("ERROR", "Simulated downstream failure", stack_trace=traceback.format_exc())
            raise HTTPException(status_code=500, detail="Simulated downstream failure")

    emit_log("INFO", "simulate-error call succeeded (no fault injected this time)")
    return {"status": "ok", "rate": rate}
