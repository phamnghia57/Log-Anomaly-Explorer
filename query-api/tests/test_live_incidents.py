import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from importlib import import_module
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from clustering.evaluation.precision_recall import evaluate
from clustering.src import incidents
from clustering.src.clustering import make_cluster_id

live_auth_stack = import_module("query-api.tests.live_auth_stack").live_auth_stack
limits = import_module("query-api.src.login_limits")

pytestmark = pytest.mark.skipif(not os.environ.get("AUTH_TEST_OPENSEARCH_URL"),
                                reason="Requires a disposable OpenSearch cluster")


@pytest.fixture()
def stack():
    password, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    with live_auth_stack(os.environ["AUTH_TEST_OPENSEARCH_URL"], "test-admin", password, secret) as service:
        with TestClient(service.app) as client:
            response = client.post("/auth/login", headers={"X-CSRF-Protection": "1"},
                                   json={"username": "test-admin", "password": password})
            assert response.status_code == 200
            auth = {"Authorization": "Bearer " + response.json()["token"]}
            yield client, service.app.state, auth


def test_incident_lifecycle_with_legacy_history_and_export(stack, monkeypatch, tmp_path):
    client, state, auth = stack
    base = datetime.now(timezone.utc).replace(microsecond=0)

    class Clock(datetime):
        current = base

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(incidents, "datetime", Clock)
    store = state.cluster_store
    signature = "order <NUM> failed"
    cluster_id = make_cluster_id("auth-test", signature)
    original = {**store.get_cluster("auth-test-cluster"), "cluster_id": cluster_id, "signature": signature}
    store.write_cluster(original)
    path = f"/clusters/{cluster_id}"
    first = client.get(path, headers=auth).json()["incident"]
    assert first["status"] == "open"
    ack = {"episode_id": first["episode_id"], "action": "acknowledge"}
    assert client.patch(path, json=ack).status_code == 401
    assert client.patch("/clusters/missing", headers=auth, json=ack).status_code == 404
    acknowledged = client.patch(path, headers=auth, json=ack)
    assert acknowledged.json()["acknowledged_by"] == "test-admin"
    assert client.patch(path, headers=auth, json=ack).json() == acknowledged.json()

    def resolution(incident, note, disposition="confirmed_incident"):
        return {"episode_id": incident["episode_id"], "action": "resolve", "note": note,
                "disposition": disposition, "window_from": incident["window_from"],
                "window_to": incident["window_to"]}

    invalid = resolution(first, "A real incident")
    invalid["window_to"] = invalid["window_from"]
    assert client.patch(path, headers=auth, json=invalid).status_code == 422

    barrier = Barrier(2)

    def resolve_concurrently(note):
        barrier.wait()
        return client.patch(path, headers=auth, json=resolution(first, note))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(resolve_concurrently, ("Network fault", "Competing note")))
    assert sorted(outcome.status_code for outcome in outcomes) == [200, 409]
    closed = next(outcome.json() for outcome in outcomes if outcome.status_code == 200)
    assert closed["acknowledged_by"] == closed["resolved_by"] == "test-admin"
    assert client.patch(path, headers=auth, json=resolution(first, closed["note"])).json() == closed
    assert client.get(path, headers=auth).json()["incident"] == closed

    def recur(offset):
        timestamp = (base + timedelta(seconds=offset)).isoformat()
        anomaly = {**original, "first_seen": timestamp, "last_seen": timestamp, "status": "anomalous"}
        store.write_history(anomaly, timestamp)
        store.write_cluster({**anomaly, "status": "normal"})
        return client.get(path, headers=auth).json()

    next_detail = recur(1)
    second = next_detail["incident"]
    assert next_detail["status"] == "normal"
    assert second["status"] == "open" and second["episode_id"] != first["episode_id"]
    assert client.patch(path, headers=auth, json=ack).status_code == 409
    Clock.current += timedelta(seconds=2)
    assert client.patch(path, headers=auth, json=resolution(second, "Noise", "false_positive")).status_code == 200
    third = recur(3)["incident"]
    Clock.current += timedelta(seconds=2)
    assert client.patch(path, headers=auth, json=resolution(third, "Recurring incident")).status_code == 200

    chart = client.get(f"{path}/history", headers=auth).json()
    assert len(chart["points"]) == 2
    assert set(chart["points"][0]) == {"cluster_id", "status", "recorded_at", "score"}
    labels = state.incident_repository.export_confirmed(base - timedelta(days=1), base + timedelta(days=1))
    assert [label["incident_id"] for label in labels] == [first["episode_id"], third["episode_id"]]
    output = tmp_path / "labels.json"
    output.write_text(json.dumps({"incidents": labels}), encoding="utf-8")
    assert evaluate([original], output)["true_positive"] == 1


def test_shared_login_limit_and_heartbeat_with_opensearch(stack, monkeypatch):
    client, state, _ = stack
    monkeypatch.setattr(limits.config, "AUTH_LOGIN_MAX_ATTEMPTS", 2)
    replicas = [limits.LoginLimiter(state.store) for _ in range(2)]
    barrier = Barrier(2)

    def reserve(instance):
        barrier.wait()
        return instance.reserve("another-user")

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservations = list(executor.map(reserve, replicas))
    assert reservations[0] == reservations[1]
    with pytest.raises(limits.LoginLimited):
        replicas[0].reserve("another-user")
    replicas[1].reset(reservations[1])
    assert replicas[0].reserve("another-user") != reservations[0]

    path = "/clustering/health"
    assert client.get(path).json()["reason"] == "missing"
    store = state.cluster_store
    now = datetime.now(timezone.utc)
    store.write_heartbeat(now.isoformat())
    assert client.get(path).status_code == 200
    store.write_heartbeat((now - timedelta(days=1)).isoformat())
    stale = client.get(path)
    assert stale.status_code == 503
    assert stale.json()["reason"] == "stale"
