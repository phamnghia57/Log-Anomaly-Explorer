from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized = False

# Gia tri hop le ve dinh dang (hex) nhung la "khong co trace", dung khi log duoc sinh ngoai request.
_EMPTY_TRACE_ID = "0" * 32
_EMPTY_SPAN_ID = "0" * 16


def setup_telemetry(service_name: str, app: FastAPI | None = None) -> None:
    """Khoi tao OpenTelemetry SDK cho service nay.

    Goi mot lan luc khoi dong, sau khi tao `app`:
        setup_telemetry(SERVICE_NAME, app)
    """
    global _initialized
    if not _initialized:
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))

        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            # Import tai day de khong bat buoc cai package exporter khi khong dung.
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

        trace.set_tracer_provider(provider)
        _initialized = True

    if app is not None:
        # Moi request vao app -> 1 server span. Bo qua /health de khong sinh trace thua.
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")

def get_current_trace_context() -> dict:
    """Tra ve {"trace_id": ..., "span_id": ...} cua request dang xu ly.

    Dung de dinh kem vao moi structured log truoc khi gui ve /ingest,
    dung theo docs/architect/contracts/log-schema.json.
    """
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return {"trace_id": _EMPTY_TRACE_ID, "span_id": _EMPTY_SPAN_ID}
    return {
        "trace_id": trace.format_trace_id(ctx.trace_id),
        "span_id": trace.format_span_id(ctx.span_id),
    }
