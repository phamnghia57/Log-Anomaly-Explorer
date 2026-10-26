"""OpenTelemetry cho query-api.

Khac demo-app (sinh trace cho request nghiep vu de co du lieu demo): o day
trace dung de QUAN SAT CHINH TANG DOC - request nao cua UI cham, cham o dau.
Dac biet huu dung cho `GET /clusters/{id}`: do tai that cho thay day la
endpoint cham nhat he thong (median 530ms, p99 1.7s - xem load-tests/README.md),
nhung truoc day khong co span nao de biet thoi gian do tieu o dau.

Khong dat OTEL_EXPORTER_OTLP_ENDPOINT thi service van chay binh thuong, chi la
khong gui span di dau (dung cho test va dev local).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE = "query-api"

_initialized = False


def setup_telemetry(app: FastAPI) -> None:
    """Goi mot lan luc khoi dong, sau khi tao `app`."""
    global _initialized
    if not _initialized:
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: SERVICE}))

        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            # Import tai day de khong bat buoc cai package exporter khi khong dung.
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

        trace.set_tracer_provider(provider)
        _initialized = True

    # Bo qua /health va /metrics: bi goi lien tuc boi healthcheck cua Docker va
    # scraper Prometheus, sinh trace rac lam day bo nho Jaeger (Jaeger trong
    # stack nay dung SPAN_STORAGE_TYPE=memory, xem docker-compose.yml).
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
