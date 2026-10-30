"""Bao ve tat ca query endpoints bang JWT that; khong can OpenSearch."""

import importlib
import secrets
from datetime import datetime, timezone
from unittest.mock import Mock

import jwt
import pytest
from fastapi.testclient import TestClient

main = importlib.import_module("query-api.src.main")
config = importlib.import_module("query-api.src.config")

PATHS = ["/search", "/clusters", "/clusters/c1", "/clusters/c1/history"]


@pytest.fixture()
def query_app(monkeypatch, admin_auth):
    log = {
        "log_id": "l1", "timestamp": "2026-01-01T00:00:00+00:00", "level": "ERROR",
        "service": "demo-web", "trace_id": "t1", "span_id": "s1", "message": "failure",
    }
    cluster = {
        "cluster_id": "c1", "score": 3.2, "status": "alerted", "log_ids": ["l1"],
        "trace_ids": ["t1"], "first_seen": log["timestamp"], "last_seen": log["timestamp"],
    }
    point = {"recorded_at": log["timestamp"], "score": 3.2, "status": "alerted"}
    logs, clusters = Mock(), Mock()
    logs.ping.return_value = True
    logs.search_with_total.return_value = ([log], 1)
    logs.get_logs.return_value = [log]
    clusters.list_clusters.return_value = [cluster]
    clusters.get_cluster.return_value = cluster
    clusters.list_history.return_value = [point]
    monkeypatch.setattr(main, "store", logs)
    monkeypatch.setattr(main, "cluster_store", clusters)
    expected = {
        "/search": {"total": 1, "results": [log]},
        "/clusters": {"total": 1, "clusters": [cluster]},
        "/clusters/c1": {**cluster, "logs": [log], "logs_total": 1},
        "/clusters/c1/history": {"cluster_id": "c1", "points": [point]},
    }
    with TestClient(main.app) as client:
        yield client, logs, clusters, expected


def assert_unauthorized(response, logs, clusters):
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing authentication token"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert not logs.mock_calls
    assert not clusters.mock_calls


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("authorization", [None, "", "Bearer", "Bearer ", "Basic credentials"])
def test_missing_or_malformed_authorization_is_401(query_app, path, authorization):
    client, logs, clusters, _ = query_app
    headers = {} if authorization is None else {"Authorization": authorization}

    assert_unauthorized(client.get(path, headers=headers), logs, clusters)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "failure",
    ["signature", "expired", "role", "unsigned", "algorithm", "malformed",
     "missing_sub", "missing_role", "missing_exp", "empty_sub"],
)
def test_invalid_tokens_are_rejected_before_storage(query_app, path, failure, caplog):
    client, logs, clusters, _ = query_app
    claims = {
        "sub": "test-admin", "role": "admin",
        "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
    }
    key, algorithm = config.JWT_SECRET, "HS256"
    if failure == "signature":
        key = secrets.token_urlsafe(48)
    elif failure == "expired":
        claims["exp"] = 1
    elif failure == "role":
        claims["role"] = "viewer"
    elif failure == "unsigned":
        key, algorithm = "", "none"
    elif failure == "algorithm":
        algorithm = "HS512"
    elif failure.startswith("missing_"):
        del claims[failure.removeprefix("missing_")]
    elif failure == "empty_sub":
        claims["sub"] = ""
    token = "not-a-jwt" if failure == "malformed" else jwt.encode(claims, key, algorithm=algorithm)

    response = client.get(path, headers={"Authorization": f"Bearer {token}"})

    assert_unauthorized(response, logs, clusters)
    assert token not in response.text + caplog.text
    assert config.JWT_SECRET not in response.text + caplog.text


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_valid_admin_preserves_response_body(query_app, admin_auth, path, scheme):
    client, _, _, expected = query_app
    token = admin_auth["Authorization"].split(" ", 1)[1]

    response = client.get(path, headers={"Authorization": f"{scheme} {token}"})

    assert response.status_code == 200
    assert response.json() == expected[path]


@pytest.mark.parametrize("path", PATHS)
def test_query_string_token_cannot_replace_authorization_header(query_app, admin_auth, path):
    client, logs, clusters, _ = query_app
    token = admin_auth["Authorization"].split(" ", 1)[1]

    response = client.get(path, params={"token": token, "access_token": token})

    assert_unauthorized(response, logs, clusters)


@pytest.mark.parametrize("path", PATHS)
def test_options_preflight_needs_no_jwt(query_app, path):
    client, logs, clusters, _ = query_app

    response = client.options(path, headers={
        "Origin": "https://frontend.example",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,content-type",
    })

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "GET" in response.headers["access-control-allow-methods"]
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert not logs.mock_calls
    assert not clusters.mock_calls


@pytest.mark.parametrize("path", PATHS)
def test_401_response_has_cors_headers_for_frontend(query_app, path):
    client, logs, clusters, _ = query_app

    response = client.get(path, headers={"Origin": "https://frontend.example"})

    assert_unauthorized(response, logs, clusters)
    assert response.headers["access-control-allow-origin"] == "*"


def test_invalid_server_config_does_not_disable_auth(query_app, admin_auth, monkeypatch):
    client, logs, clusters, _ = query_app
    monkeypatch.setattr(config, "JWT_SECRET", None)

    response = client.get("/search", headers=admin_auth)

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication unavailable"}
    assert not logs.mock_calls
    assert not clusters.mock_calls
