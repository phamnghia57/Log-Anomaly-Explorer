import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from jsonschema import validate
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

sys.path.insert(0, str(Path(__file__).parents[1]))

from src import main


@pytest.fixture(scope="module")
def live_app():
    # Dung TCP that de kiem tra propagation qua HTTP, khong dung ASGITransport.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(main.app, lifespan="off", log_level="critical", access_log=False)
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "Uvicorn did not start"
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive(), "Uvicorn did not stop"


@pytest.fixture(scope="module")
def span_exporter():
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    trace.get_tracer_provider().add_span_processor(processor)
    yield exporter
    processor.shutdown()


@pytest.fixture()
def traced_app(monkeypatch, live_app, span_exporter):
    logs = []
    monkeypatch.setattr(main._http, "post", lambda url, *, json: logs.append(json))
    monkeypatch.setattr(main, "PAYMENT_URL", f"{live_app}/payment")
    span_exporter.clear()
    with httpx.Client(base_url=live_app, timeout=5.0, trust_env=False) as client:
        yield client, logs, span_exporter
    span_exporter.clear()


def validate_logs(logs):
    schema = json.loads(
        (Path(__file__).parents[2] / "docs/architect/contracts/log-schema.json").read_text()
    )
    for payload in logs:
        validate(payload, schema)


def checkout_spans(exporter):
    # Response co the toi client truoc khi server ket thuc/export span.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        spans = exporter.get_finished_spans()
        if any(s.kind == SpanKind.SERVER and s.attributes.get("http.route") == "/checkout"
               for s in spans):
            return spans
        time.sleep(0.01)
    pytest.fail("Checkout server span was not exported")


@pytest.mark.parametrize("incoming_context", [False, True])
def test_checkout_calls_payment_over_http_in_one_trace(traced_app, incoming_context):
    client, logs, exporter = traced_app
    headers = {}
    if incoming_context:
        headers = {
            "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
            "tracestate": "demo=checkout",
        }

    response = client.post("/checkout", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "payment": {"status": "approved", "amount": 100000, "currency": "VND"},
    }
    spans = checkout_spans(exporter)
    servers = {s.attributes["http.route"]: s for s in spans if s.kind == SpanKind.SERVER}
    clients = [s for s in spans if s.kind == SpanKind.CLIENT]
    assert set(servers) == {"/checkout", "/payment"}
    assert len(clients) == 1
    checkout, payment, downstream = servers["/checkout"], servers["/payment"], clients[0]

    assert checkout.context.trace_id != 0
    assert checkout.context.trace_id == downstream.context.trace_id == payment.context.trace_id
    assert len({s.context.span_id for s in (checkout, downstream, payment)}) == 3
    assert downstream.parent.span_id == checkout.context.span_id
    assert payment.parent.span_id == downstream.context.span_id
    assert payment.parent.is_remote
    assert downstream.attributes["http.url"] == main.PAYMENT_URL
    assert downstream.attributes["http.status_code"] == 200
    assert checkout.start_time <= downstream.start_time <= payment.start_time
    assert payment.end_time <= downstream.end_time <= checkout.end_time
    if incoming_context:
        assert checkout.context.trace_id == int("1234567890abcdef1234567890abcdef", 16)
        assert checkout.parent.span_id == int("1234567890abcdef", 16)
        assert checkout.parent.is_remote
        assert payment.context.trace_state.get("demo") == "checkout"
    else:
        assert checkout.parent is None

    assert [payload["message"] for payload in logs] == [
        "Checkout started", "Payment approved", "Checkout completed"
    ]
    validate_logs(logs)
    assert {payload["trace_id"] for payload in logs} == {
        trace.format_trace_id(checkout.context.trace_id)
    }
    assert logs[0]["span_id"] == logs[2]["span_id"] == trace.format_span_id(checkout.context.span_id)
    assert logs[1]["span_id"] == trace.format_span_id(payment.context.span_id)


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [("connection", 502), ("timeout", 504), ("http_error", 502)],
)
def test_checkout_reports_downstream_failures(traced_app, monkeypatch, failure, expected_status):
    client, logs, exporter = traced_app

    def fail_payment(request):
        if failure == "connection":
            raise httpx.ConnectError("Payment unavailable", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("Payment timed out", request=request)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(fail_payment)) as payment_client:
        monkeypatch.setattr(main, "_payment_http", payment_client)
        response = client.post("/checkout")

    assert response.status_code == expected_status
    assert logs[-1]["level"] == "ERROR"
    assert logs[-1]["message"] == response.json()["detail"]
    assert logs[-1]["stack_trace"]
    assert "Checkout completed" not in [payload["message"] for payload in logs]
    validate_logs(logs)
    downstream = next(s for s in checkout_spans(exporter) if s.kind == SpanKind.CLIENT)
    assert downstream.status.status_code == StatusCode.ERROR
    assert downstream.events


def test_health_still_excluded_from_tracing(traced_app):
    client, logs, exporter = traced_app

    assert client.get("/health").status_code == 200
    assert not exporter.get_finished_spans()
    assert not logs
