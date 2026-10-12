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
import time
import traceback
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException

from .telemetry import get_current_trace_context, setup_telemetry

SERVICE_NAME = "demo-web"
INGESTION_URL = os.environ.get("INGESTION_URL", "http://localhost:8000/ingest")

app = FastAPI(title="Log Anomaly Explorer - Demo App")

setup_telemetry(SERVICE_NAME, app)

# Dung chung 1 client de tai su dung ket noi toi Ingestion (nhanh hon httpx.post moi lan).
_http = httpx.Client(timeout=2.0)


def emit_log(level: str, message: str, stack_trace: str | None = None) -> None:
    trace_ctx = get_current_trace_context()
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
        _http.post(INGESTION_URL, json=payload)
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


@app.get("/api/mobile/items")
def list_mobile_items() -> dict:
    """Endpoint happy-path mo phong client mobile."""
    emit_log("INFO", "Listed items successfully (mobile client)")
    return {"items": ["item-1", "item-2", "item-3"], "client": "mobile"}


@app.get("/simulate-error")
def simulate_error(
    rate: float = 0.3,
    fault: Literal["downstream", "timeout"] = "downstream",
) -> dict:
    """Fault injection co chu dich.

    Goi endpoint nay lap lai (vd. bang load-tests/locustfile.py) voi `rate` khac nhau
    de tao ra cac giai doan bat thuong co kiem soat, phuc vu:
      - GitHub evidence "fault injection"
      - Du lieu dau vao cho "labeled incidents" (Nam tu gan nhan
        giai doan nay la mot incident that trong qua trinh danh gia precision/recall)

    `fault=downstream` tao loi 500; `fault=timeout` mo phong downstream timeout
    va tra ve 504. Ca hai truong hop van gui structured log hop le.
    """
    if random.random() < rate:
        if fault == "timeout":
            try:
                time.sleep(0.1)
                raise TimeoutError("Simulated downstream timeout")
            except TimeoutError:
                emit_log("ERROR", "Simulated downstream timeout", stack_trace=traceback.format_exc())
                raise HTTPException(status_code=504, detail="Simulated downstream timeout")

        try:
            raise RuntimeError("Simulated downstream failure")
        except RuntimeError:
            emit_log("ERROR", "Simulated downstream failure", stack_trace=traceback.format_exc())
            raise HTTPException(status_code=500, detail="Simulated downstream failure")

    emit_log("INFO", "simulate-error call succeeded (no fault injected this time)")
    return {"status": "ok", "rate": rate}
