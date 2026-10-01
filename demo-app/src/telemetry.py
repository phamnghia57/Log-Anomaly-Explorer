"""
Cau hinh OpenTelemetry cho demo-app.

TODO (Manh):
- Khoi tao TracerProvider + exporter (OTLP) tro ve collector / truc tiep ve ingestion.
- Dam bao moi request sinh ra trace_id/span_id duoc dinh kem vao log qua `get_current_trace_context()`.
"""

from __future__ import annotations


def setup_telemetry(service_name: str) -> None:
    """Khoi tao OpenTelemetry SDK cho service nay.

    TODO: thay the bang cau hinh TracerProvider/OTLP exporter that.
    """
    raise NotImplementedError("Manh: cau hinh OpenTelemetry SDK tai day")


def get_current_trace_context() -> dict:
    """Tra ve {"trace_id": ..., "span_id": ...} cua request dang xu ly.

    Dung de dinh kem vao moi structured log truoc khi gui ve /ingest,
    dung theo docs/contracts/log-schema.json.
    """
    raise NotImplementedError("Manh: lay trace context tu OpenTelemetry tai day")
