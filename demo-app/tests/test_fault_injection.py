import sys
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from jsonschema import ValidationError, validate
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))

from src import main


@pytest.fixture()
def client(monkeypatch):
    logs = []
    monkeypatch.setattr(
        main._http,
        "post",
        lambda url, *, json: logs.append(json),
    )
    with TestClient(main.app) as test_client:
        yield test_client, logs


@pytest.mark.parametrize(
    ("path", "service"),
    [("/api/items", "demo-web"), ("/api/mobile/items", "demo-mobile-api")],
)
def test_baselines_work_and_identify_platform(client, path, service):
    response = client[0].get(path)
    logs = client[1]

    assert response.status_code == 200
    assert response.json()["items"]
    assert logs[-1]["metadata"]["platform"] == (
        "mobile-api" if "mobile" in path else "web"
    )
    assert logs[-1]["metadata"]["error_type"] == "baseline"


@pytest.mark.parametrize(
    ("path", "fault", "status"),
    [
        ("/api/items", "value", 422),
        ("/api/items", "connection", 502),
        ("/api/items", "runtime", 500),
        ("/api/mobile/items", "value", 422),
        ("/api/mobile/items", "connection", 502),
        ("/api/mobile/items", "runtime", 500),
    ],
)
def test_all_platform_faults_emit_schema_shaped_traceable_logs(client, path, fault, status):
    response = client[0].get(path, params={"fault": fault, "rate": 1, "seed": 1})
    logs = client[1]

    assert response.status_code == status
    payload = logs[-1]
    schema = json.loads(
        (Path(__file__).parents[2] / "docs/architect/contracts/log-schema.json").read_text()
    )
    validate(payload, schema)
    assert payload["level"] == "ERROR"
    assert payload["metadata"]["error_type"] == fault
    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16
    assert payload["trace_id"] != "0" * 32
    assert payload["span_id"] != "0" * 16


def test_connection_fault_is_deterministic_without_network_access(client):
    response = client[0].get(
        "/api/items", params={"fault": "connection", "rate": 1, "seed": 1}
    )

    assert response.status_code == 502
    assert client[1][-1]["metadata"]["error_type"] == "connection"


@pytest.mark.parametrize(
    ("path", "platform", "service"),
    [
        ("/api/items", "web", "demo-web"),
        ("/api/mobile/items", "mobile-api", "demo-mobile-api"),
        ("/simulate-error", "web", "demo-web"),
        ("/simulate-error", "mobile-api", "demo-mobile-api"),
    ],
)
@pytest.mark.parametrize("ingestion_status", [202, 400, 503])
def test_bad_schema_posts_invalid_payload_directly(
    client, monkeypatch, path, platform, service, ingestion_status
):
    ingestion_url = "http://ingestion.test/custom-ingest"
    monkeypatch.setattr(main, "INGESTION_URL", ingestion_url)
    post = Mock(return_value=httpx.Response(ingestion_status))
    monkeypatch.setattr(main._http, "post", post)
    emit_log = Mock()
    monkeypatch.setattr(main, "emit_log", emit_log)
    params = {"fault": "bad_schema", "rate": 1, "seed": 1}
    if path == "/simulate-error":
        params["platform"] = platform

    response = client[0].get(path, params=params)

    assert response.status_code == 502
    emit_log.assert_not_called()
    post.assert_called_once()
    payload = post.call_args.kwargs["json"]
    post.assert_called_once_with(ingestion_url, json=payload)
    assert payload["service"] == service
    assert payload["metadata"] == {"platform": platform, "error_type": "bad_schema"}
    assert payload["message"] == response.json()["detail"]
    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16
    assert payload["trace_id"] != "0" * 32
    assert payload["span_id"] != "0" * 16
    schema = json.loads(
        (Path(__file__).parents[2] / "docs/architect/contracts/log-schema.json").read_text()
    )
    with pytest.raises(ValidationError) as error:
        validate(payload, schema)
    assert error.value.validator == "enum"
    assert list(error.value.path) == ["level"]
    assert payload["level"] == "CRITICAL"
    validate({**payload, "level": "ERROR"}, schema)


@pytest.mark.parametrize("transport_error", [httpx.ConnectError, httpx.ReadTimeout])
def test_bad_schema_returns_502_on_log_transport_error(client, monkeypatch, transport_error):
    post = Mock(side_effect=transport_error("Ingestion unavailable"))
    monkeypatch.setattr(main._http, "post", post)
    emit_log = Mock()
    monkeypatch.setattr(main, "emit_log", emit_log)

    response = client[0].get("/api/items", params={"fault": "bad_schema", "rate": 1})

    assert response.status_code == 502
    post.assert_called_once()
    emit_log.assert_not_called()


@pytest.mark.parametrize(("fault", "status"), [("runtime", 500), ("bad_schema", 502)])
def test_seed_reproduces_trigger_decision(client, fault, status):
    first = client[0].get(
        "/api/items", params={"fault": fault, "rate": 0.5, "seed": 1}
    )
    second = client[0].get(
        "/api/items", params={"fault": fault, "rate": 0.5, "seed": 1}
    )
    opposite = client[0].get(
        "/api/items", params={"fault": fault, "rate": 0.5, "seed": 2}
    )

    assert (first.status_code, second.status_code, opposite.status_code) == (
        status,
        status,
        200,
    )
    assert client[1][-1]["metadata"]["error_type"] == "baseline"
    schema = json.loads(
        (Path(__file__).parents[2] / "docs/architect/contracts/log-schema.json").read_text()
    )
    validate(client[1][-1], schema)


@pytest.mark.parametrize("path", ["/api/items", "/api/mobile/items"])
@pytest.mark.parametrize("fault", ["runtime", "bad_schema"])
def test_rate_zero_never_triggers_fault(client, path, fault):
    response = client[0].get(
        path, params={"fault": fault, "rate": 0, "seed": 1}
    )

    assert response.status_code == 200
    assert client[1][-1]["metadata"]["error_type"] == "baseline"


def test_simulate_error_keeps_legacy_faults_and_supports_platform(client):
    timeout = client[0].get(
        "/simulate-error",
        params={"fault": "timeout", "rate": 1, "platform": "mobile-api", "seed": 1},
    )
    downstream = client[0].get(
        "/simulate-error", params={"fault": "downstream", "rate": 1, "seed": 1}
    )

    assert timeout.status_code == 504
    assert downstream.status_code == 500
    assert client[1][-2]["metadata"]["platform"] == "mobile-api"
    assert client[1][-1]["metadata"]["error_type"] == "runtime"
