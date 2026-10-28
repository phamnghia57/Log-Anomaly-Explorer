import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from jsonschema import ValidationError, validate
from opentelemetry import context, trace
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
def captured_trace(monkeypatch, span_exporter):
    logs = []
    monkeypatch.setattr(main._http, "post", lambda url, *, json: logs.append(json))
    span_exporter.clear()
    yield logs, span_exporter
    span_exporter.clear()


@pytest.fixture()
def payment_requests():
    return []


@pytest.fixture()
def mocked_app(monkeypatch, captured_trace, payment_requests):
    # Mock chi tang transport; van chay endpoint payment va FastAPI instrumentation.
    def forward_payment(request):
        payment_requests.append(request)
        # Mo phong ranh gioi process: payment chi nhan context tu HTTP headers.
        token = context.attach(context.Context())
        try:
            response = payment.post(
                request.url.path, content=request.content, headers=request.headers
            )
        finally:
            context.detach(token)
        return httpx.Response(response.status_code, content=response.content)

    monkeypatch.setattr(main, "PAYMENT_URL", "http://payment.test/payment")
    with TestClient(main.app) as payment:
        with httpx.Client(transport=httpx.MockTransport(forward_payment)) as payment_client:
            monkeypatch.setattr(main, "_payment_http", payment_client)
            with TestClient(main.app) as client:
                yield client, *captured_trace


@pytest.fixture()
def traced_app(monkeypatch, live_app, captured_trace):
    monkeypatch.setattr(main, "PAYMENT_URL", f"{live_app}/payment")
    with httpx.Client(base_url=live_app, timeout=5.0, trust_env=False) as client:
        yield client, *captured_trace


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
@pytest.mark.parametrize("app_fixture", ["mocked_app", "traced_app"])
def test_checkout_calls_payment_over_http_in_one_trace(request, app_fixture, incoming_context):
    client, logs, exporter = request.getfixturevalue(app_fixture)
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
    assert all(s.context.span_id != 0 for s in spans)
    assert len({s.context.span_id for s in spans}) == len(spans)
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


def test_checkout_injects_client_span_context_into_payment_headers(mocked_app, payment_requests):
    client, _, exporter = mocked_app
    headers = {
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
        "tracestate": "demo=checkout",
    }

    assert client.post("/checkout", headers=headers).status_code == 200

    assert len(payment_requests) == 1
    request = payment_requests[0]
    assert request.method == "POST"
    assert str(request.url) == main.PAYMENT_URL
    assert json.loads(request.content) == {"amount": 100000, "currency": "VND"}
    spans = checkout_spans(exporter)
    downstream = next(s for s in spans if s.kind == SpanKind.CLIENT)
    expected_traceparent = (
        f"00-{trace.format_trace_id(downstream.context.trace_id)}-"
        f"{trace.format_span_id(downstream.context.span_id)}-01"
    )
    assert request.headers["traceparent"] == expected_traceparent
    assert request.headers["traceparent"] != headers["traceparent"]
    assert request.headers["tracestate"] == headers["tracestate"]
    payment = next(s for s in spans if s.kind == SpanKind.SERVER
                   and s.attributes["http.route"] == "/payment")
    assert payment.parent.is_remote
    assert payment.parent.span_id == downstream.context.span_id


@pytest.mark.parametrize(
    ("failure", "expected_status", "error_type"),
    [
        (httpx.ConnectError, 502, "downstream"),
        (httpx.ReadTimeout, 504, "timeout"),
        (httpx.ConnectTimeout, 504, "timeout"),
        (400, 502, "downstream"),
        (503, 502, "downstream"),
    ],
)
def test_checkout_reports_downstream_failures(
    mocked_app, monkeypatch, failure, expected_status, error_type
):
    client, logs, exporter = mocked_app
    requests = []

    def fail_payment(request):
        requests.append(request)
        if isinstance(failure, int):
            return httpx.Response(failure)
        raise failure("Payment unavailable", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail_payment)) as payment_client:
        monkeypatch.setattr(main, "_payment_http", payment_client)
        response = client.post("/checkout")

    assert response.status_code == expected_status
    assert len(requests) == 1
    assert logs[-1]["level"] == "ERROR"
    assert logs[-1]["message"] == response.json()["detail"]
    assert logs[-1]["stack_trace"]
    assert logs[-1]["metadata"]["error_type"] == error_type
    assert "Checkout completed" not in [payload["message"] for payload in logs]
    validate_logs(logs)
    spans = checkout_spans(exporter)
    downstream = next(s for s in spans if s.kind == SpanKind.CLIENT)
    checkout = next(s for s in spans if s.kind == SpanKind.SERVER)
    assert downstream.status.status_code == StatusCode.ERROR
    assert downstream.parent.span_id == checkout.context.span_id
    assert downstream.context.trace_id == checkout.context.trace_id
    assert logs[-1]["trace_id"] == trace.format_trace_id(checkout.context.trace_id)
    assert logs[-1]["span_id"] == trace.format_span_id(checkout.context.span_id)
    assert checkout.attributes["http.status_code"] == expected_status
    exception = next(event for event in downstream.events if event.name == "exception")
    expected_exception = "httpx.HTTPStatusError" if isinstance(failure, int) else (
        f"httpx.{failure.__name__}"
    )
    assert exception.attributes["exception.type"] == expected_exception
    if isinstance(failure, int):
        assert downstream.attributes["http.status_code"] == failure


@pytest.mark.parametrize("path", ["/api/items", "/api/mobile/items"])
@pytest.mark.parametrize(
    ("fault", "expected_status", "error_type"),
    [
        ("value", 422, "value"),
        ("connection", 502, "connection"),
        ("runtime", 500, "runtime"),
        ("downstream", 500, "runtime"),
        ("timeout", 504, "runtime"),
        ("bad_schema", 502, "bad_schema"),
    ],
)
def test_faults_keep_their_own_trace_after_checkout(
    mocked_app, payment_requests, path, fault, expected_status, error_type
):
    client, logs, exporter = mocked_app
    assert client.post("/checkout").status_code == 200
    checkout_trace_id = logs[0]["trace_id"]

    response = client.get(path, params={"fault": fault, "rate": 1, "seed": 1})

    assert response.status_code == expected_status
    assert len(payment_requests) == 1
    payload = logs[-1]
    assert payload["metadata"]["error_type"] == error_type
    assert payload["metadata"]["platform"] == ("mobile-api" if "mobile" in path else "web")
    assert payload["trace_id"] != checkout_trace_id
    server = next(s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER
                  and s.attributes["http.route"] == path)
    assert server.parent is None
    assert payload["trace_id"] == trace.format_trace_id(server.context.trace_id)
    assert payload["span_id"] == trace.format_span_id(server.context.span_id)
    validate_logs(logs[:-1])
    if fault == "bad_schema":
        assert payload["level"] == "CRITICAL"
        with pytest.raises(ValidationError) as error:
            validate_logs([payload])
        assert error.value.validator == "enum"
        assert list(error.value.path) == ["level"]
    else:
        assert payload["level"] == "ERROR"
        validate_logs([payload])


def test_health_still_excluded_from_tracing(mocked_app):
    client, logs, exporter = mocked_app

    assert client.get("/health").status_code == 200
    assert not exporter.get_finished_spans()
    assert not logs
