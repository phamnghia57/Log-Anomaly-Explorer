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
from fastapi import FastAPI, HTTPException, Query
from opentelemetry import trace
from opentelemetry.propagate import inject
from pydantic import BaseModel, Field

from .telemetry import get_current_trace_context, setup_telemetry

SERVICE_NAME = "demo-web"
MOBILE_SERVICE_NAME = "demo-mobile-api"
INGESTION_URL = os.environ.get("INGESTION_URL", "http://localhost:8000/ingest")
PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://127.0.0.1:8001/payment")

app = FastAPI(title="Log Anomaly Explorer - Demo App")

setup_telemetry(SERVICE_NAME, app)

# Dung chung 1 client de tai su dung ket noi toi Ingestion (nhanh hon httpx.post moi lan).
_http = httpx.Client(timeout=2.0)
# Payment dung HTTP that toi cung app; khong di qua proxy cua moi truong.
_payment_http = httpx.Client(timeout=2.0, trust_env=False)
_tracer = trace.get_tracer(__name__)


def emit_log(
    level: str,
    message: str,
    stack_trace: str | None = None,
    *,
    platform: Literal["web", "mobile-api"] = "web",
    error_type: str | None = None,
) -> None:
    trace_ctx = get_current_trace_context()
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": MOBILE_SERVICE_NAME if platform == "mobile-api" else SERVICE_NAME,
        "trace_id": trace_ctx["trace_id"],
        "span_id": trace_ctx["span_id"],
        "message": message,
        "stack_trace": stack_trace,
        "metadata": {
            "platform": platform,
            "error_type": error_type or "baseline",
        },
    }
    try:
        _http.post(INGESTION_URL, json=payload)
    except httpx.HTTPError:
        # Khong de loi gui log lam sap ung dung demo.
        pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


class PaymentRequest(BaseModel):
    amount: int = Field(gt=0)
    currency: Literal["VND"] = "VND"


@app.post("/payment")
def payment(request: PaymentRequest) -> dict:
    """Mo phong xu ly thanh toan trong server span nhan tu traceparent."""
    emit_log("INFO", "Payment approved")
    return {"status": "approved", "amount": request.amount, "currency": request.currency}


@app.post("/checkout")
def checkout() -> dict:
    """Checkout goi payment qua HTTP, cung trace nhung khac span."""
    emit_log("INFO", "Checkout started")
    try:
        with _tracer.start_as_current_span(
            "POST /payment",
            kind=trace.SpanKind.CLIENT,
            attributes={"http.method": "POST", "http.url": PAYMENT_URL},
        ) as span:
            headers = {}
            # Truyen context cua CLIENT span; FastAPI instrumentation tu extract
            # o /payment de tao SERVER span con, giu nguyen trace_id.
            inject(headers)
            response = _payment_http.post(
                PAYMENT_URL,
                json={"amount": 100000, "currency": "VND"},
                headers=headers,
            )
            span.set_attribute("http.status_code", response.status_code)
            response.raise_for_status()
    except httpx.TimeoutException:
        message = "Checkout failed: payment timed out"
        emit_log("ERROR", message, stack_trace=traceback.format_exc(), error_type="timeout")
        raise HTTPException(status_code=504, detail=message)
    except httpx.HTTPError:
        message = "Checkout failed: payment unavailable"
        emit_log("ERROR", message, stack_trace=traceback.format_exc(), error_type="downstream")
        raise HTTPException(status_code=502, detail=message)

    emit_log("INFO", "Checkout completed")
    return {"status": "completed", "payment": response.json()}


Fault = Literal["value", "connection", "runtime", "downstream", "timeout", "bad_schema"]


def _fault_is_triggered(rate: float, seed: int | None) -> bool:
    generator = random.Random(seed) if seed is not None else random
    return generator.random() < rate


def _inject_fault(
    fault: Fault,
    *,
    platform: Literal["web", "mobile-api"],
) -> None:
    if fault == "bad_schema":
        message = "Simulated ingestion schema validation failure"
        trace_ctx = get_current_trace_context()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "CRITICAL",  # Co chu dich: khong thuoc enum trong log-schema.json.
            "service": MOBILE_SERVICE_NAME if platform == "mobile-api" else SERVICE_NAME,
            "trace_id": trace_ctx["trace_id"],
            "span_id": trace_ctx["span_id"],
            "message": message,
            "stack_trace": None,
            "metadata": {"platform": platform, "error_type": "bad_schema"},
        }
        try:
            _http.post(INGESTION_URL, json=payload)
        except httpx.HTTPError:
            # Best-effort nhu emit_log(), nhung gui truc tiep payload sai schema.
            pass
        raise HTTPException(status_code=502, detail=message)

    if fault == "value":
        message = "Simulated validation failure: required item data is invalid"
        emit_log("ERROR", message, platform=platform, error_type="value")
        raise HTTPException(status_code=422, detail=message)

    if fault == "connection":
        try:
            request = httpx.Request("GET", "http://downstream.invalid/health")
            raise httpx.ConnectError(
                "Simulated connection refused by downstream dependency",
                request=request,
            )
        except httpx.ConnectError:
            message = "Simulated connection failure: downstream dependency unreachable"
            emit_log("ERROR", message, stack_trace=traceback.format_exc(),
                     platform=platform, error_type="connection")
            raise HTTPException(status_code=502, detail=message)

    if fault == "timeout":
        try:
            time.sleep(0.1)
            raise TimeoutError("Simulated downstream timeout")
        except TimeoutError:
            message = "Simulated downstream timeout"
            emit_log("ERROR", message, stack_trace=traceback.format_exc(),
                     platform=platform, error_type="runtime")
            raise HTTPException(status_code=504, detail=message)

    if fault == "runtime" or fault == "downstream":
        try:
            raise RuntimeError(
                "Simulated runtime failure"
                if fault == "runtime"
                else "Simulated downstream failure"
            )
        except RuntimeError:
            message = (
                "Simulated runtime failure"
                if fault == "runtime"
                else "Simulated downstream failure"
            )
            emit_log("ERROR", message, stack_trace=traceback.format_exc(),
                     platform=platform, error_type="runtime")
            raise HTTPException(status_code=500, detail=message)


def _list_items(
    *,
    platform: Literal["web", "mobile-api"],
    fault: Fault | None,
    rate: float,
    seed: int | None,
) -> dict:
    if fault and _fault_is_triggered(rate, seed):
        _inject_fault(fault, platform=platform)

    emit_log("INFO", "Listed items successfully", platform=platform)
    result = {"items": ["item-1", "item-2", "item-3"]}
    if platform == "mobile-api":
        result["client"] = "mobile"
    return result


@app.get("/api/items")
def list_items(
    fault: Fault | None = None,
    rate: float = Query(1.0, ge=0.0, le=1.0),
    seed: int | None = None,
) -> dict:
    """Endpoint happy-path binh thuong, dung de tao log nen (baseline)."""
    return _list_items(platform="web", fault=fault, rate=rate, seed=seed)


@app.get("/api/mobile/items")
def list_mobile_items(
    fault: Fault | None = None,
    rate: float = Query(1.0, ge=0.0, le=1.0),
    seed: int | None = None,
) -> dict:
    """Endpoint happy-path mo phong client mobile."""
    return _list_items(platform="mobile-api", fault=fault, rate=rate, seed=seed)


@app.get("/simulate-error")
def simulate_error(
    rate: float = Query(0.3, ge=0.0, le=1.0),
    fault: Fault = "downstream",
    platform: Literal["web", "mobile-api"] = "web",
    seed: int | None = None,
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
    if _fault_is_triggered(rate, seed):
        _inject_fault(fault, platform=platform)

    emit_log("INFO", "simulate-error call succeeded (no fault injected this time)",
             platform=platform)
    return {"status": "ok", "rate": rate, "platform": platform}
