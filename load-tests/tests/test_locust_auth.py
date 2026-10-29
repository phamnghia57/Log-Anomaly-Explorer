"""Exercise real Locust HttpSession/events with a mocked requests transport."""

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import time
from pathlib import Path

# These synchronous tests mock Session.send; no global gevent monkey patch is needed.
os.environ.setdefault("LOCUST_SKIP_MONKEY_PATCH", "1")

import pytest
import requests
from locust.env import Environment
from locust.exception import StopUser

spec = importlib.util.spec_from_file_location("load_test_locustfile", Path(__file__).parents[1] / "locustfile.py")
locustfile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locustfile)


def _jwt():
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode({"sub": "load-test-admin", "role": "admin", "exp": int(time.time()) + 3600})
    digest = hmac.new(secrets.token_bytes(48), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


@pytest.fixture()
def query_user(monkeypatch):
    credentials = {"username": "load-test-admin", "password": secrets.token_urlsafe(32)}
    monkeypatch.setenv("QUERY_API_USERNAME", credentials["username"])
    monkeypatch.setenv("QUERY_API_PASSWORD", credentials["password"])
    state = {"status": 200, "body": {"token": _jwt()}, "network_error": False}
    sent, events = [], []

    def send(session, request, **kwargs):
        sent.append(request)
        if state["network_error"]:
            raise requests.ConnectionError("Test transport unavailable")
        response = requests.Response()
        response.status_code = state["status"] if request.method == "POST" else 200
        body = state["body"] if request.method == "POST" else {"clusters": [{"cluster_id": "real-cluster"}]}
        response._content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        response.url = request.url
        response.request = request
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    environment = Environment(user_classes=[locustfile.QueryUser])
    environment.events.request.add_listener(lambda **event: events.append(event))
    user = locustfile.QueryUser(environment)
    yield user, state, sent, events, credentials
    user.client.close()


def test_login_precedes_all_tasks_and_reuses_the_returned_token(query_user):
    user, state, sent, events, credentials = query_user
    user.on_start()
    assert user.cluster_ids == []
    assert user.client.headers["Authorization"] == f"Bearer {state['body']['token']}"
    user.search_logs()
    user.search_with_filter()
    user.list_clusters()
    user.incident_view()

    assert [request.method for request in sent] == ["POST", "GET", "GET", "GET", "GET"]
    assert sent[0].url.endswith("/auth/login")
    assert json.loads(sent[0].body) == credentials
    assert "Authorization" not in sent[0].headers
    assert [request.path_url.split("?")[0] for request in sent[1:]] == [
        "/search", "/search", "/clusters", "/clusters/real-cluster",
    ]
    assert all(request.headers["Authorization"] == f"Bearer {state['body']['token']}" for request in sent[1:])
    assert user.cluster_ids == ["real-cluster"]
    assert events[0]["request_type"] == "POST"
    assert events[0]["name"] == "POST /auth/login"
    assert events[0]["exception"] is None


@pytest.mark.parametrize("name", ["QUERY_API_USERNAME", "QUERY_API_PASSWORD"])
@pytest.mark.parametrize("value", [None, "", " \t"])
def test_missing_credentials_stop_before_any_http_request(query_user, monkeypatch, caplog, name, value):
    user, _, sent, _, credentials = query_user
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    user.client.headers["Authorization"] = "Bearer stale-test-token"
    with pytest.raises(StopUser):
        user.on_start()

    assert user.cluster_ids == []
    assert sent == []
    assert "Authorization" not in user.client.headers
    assert "QUERY_API_USERNAME and QUERY_API_PASSWORD" in caplog.text
    assert credentials["password"] not in caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 500, 503])
def test_failed_login_is_counted_and_stops_the_user_without_leaking_credentials(query_user, caplog, status):
    user, state, sent, events, credentials = query_user
    state.update(status=status, body={"detail": credentials["password"]})
    with pytest.raises(StopUser):
        user.on_start()

    assert len(sent) == 1
    assert "Authorization" not in user.client.headers
    assert len(events) == 1
    assert events[0]["name"] == "POST /auth/login"
    assert events[0]["exception"] is not None
    assert f"HTTP {status}" in str(events[0]["exception"])
    assert credentials["password"] not in str(events[0]["exception"]) + caplog.text


@pytest.mark.parametrize("body", [
    "not-json", None, [], {}, {"token": None}, {"token": 123}, {"token": ""},
    {"token": "not-a-jwt"}, {"token": "header.payload."}, {"token": "header.payload.signature\n"},
])
def test_malformed_login_response_is_counted_as_failure_and_stops_user(query_user, body):
    user, state, sent, events, _ = query_user
    state["body"] = body
    with pytest.raises(StopUser):
        user.on_start()

    assert len(sent) == 1
    assert "Authorization" not in user.client.headers
    assert events[0]["exception"] is not None
    assert "invalid JWT response" in str(events[0]["exception"])


def test_network_failure_is_counted_and_stops_user(query_user):
    user, state, sent, events, _ = query_user
    state["network_error"] = True
    with pytest.raises(StopUser):
        user.on_start()

    assert len(sent) == 1
    assert "Authorization" not in user.client.headers
    assert events[0]["exception"] is not None


def test_each_user_has_its_own_login_and_token(query_user):
    first, state, sent, _, _ = query_user
    first.on_start()
    first_token = first.client.headers["Authorization"]
    state["body"] = {"token": _jwt()}
    second = locustfile.QueryUser(first.environment)
    try:
        second.on_start()
        assert second.client.headers["Authorization"] != first_token
        assert first.client.headers["Authorization"] == first_token
        assert len(sent) == 2
    finally:
        second.client.close()
