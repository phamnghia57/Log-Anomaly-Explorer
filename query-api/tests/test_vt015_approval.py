"""VT-015 contract tests. No production imports for not-yet-created modules.

Proposed injection seam: app.state.approval_repository with get(cluster_id)
and create(document), returning True on first create, False on conflict.
The atomic fake is a unit/API double, not proof of OpenSearch concurrency.
"""
import importlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from fastapi.testclient import TestClient
from ingestion.src.storage import StorageError

main = importlib.import_module("query-api.src.main")
config = importlib.import_module("query-api.src.config")


class ApprovalDouble:
    def __init__(self):
        self.documents = {}
        self.writes = 0
        self.lock = Lock()
        self.fail = False

    def get(self, cluster_id):
        with self.lock:
            return deepcopy(self.documents.get(cluster_id))

    def create(self, document):
        with self.lock:
            if self.fail:
                raise StorageError("approval storage unavailable")
            key = document["cluster_id"]
            if key in self.documents:
                return False
            self.documents[key] = deepcopy(document)
            self.writes += 1
            return True


@pytest.fixture
def vt015(monkeypatch, admin_auth):
    log = {"log_id": "l1", "message": "original"}
    cluster = {"cluster_id": "c1", "score": 3.2, "status": "alerted", "log_ids": ["l1"]}
    logs, clusters = Mock(), Mock()
    logs.search_with_total.return_value = ([deepcopy(log)], 1)
    logs.get_logs.return_value = [deepcopy(log)]
    clusters.list_clusters.return_value = [deepcopy(cluster)]
    clusters.get_cluster.return_value = deepcopy(cluster)
    clusters.list_history.return_value = []
    approvals = ApprovalDouble()
    monkeypatch.setattr(main, "store", logs)
    monkeypatch.setattr(main, "cluster_store", clusters)
    monkeypatch.setattr(main.app.state, "approval_repository", approvals, raising=False)

    def headers(role="reviewer", actor="reviewer-a", expired=False, invalid=False):
        claims = {"sub": actor, "role": role, "exp": 1 if expired else int(datetime.now(timezone.utc).timestamp()) + 3600}
        token = jwt.encode(claims, "wrong-key-with-at-least-32-bytes!!" if invalid else config.JWT_SECRET, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, headers=headers, logs=logs, clusters=clusters,
                              approvals=approvals, cluster=cluster, log=log)


def assert_original_untouched(s):
    assert s.clusters.get_cluster.return_value == s.cluster
    assert s.logs.get_logs.return_value == [s.log]
    assert set(call[0] for call in s.logs.mock_calls) <= {"search_with_total", "get_logs"}
    assert set(call[0] for call in s.clusters.mock_calls) <= {"get_cluster", "list_clusters", "list_history"}


@pytest.mark.parametrize("role", ["reviewer", "admin"])
@pytest.mark.parametrize("path", ["/search", "/clusters", "/clusters/c1", "/clusters/c1/history"])
def test_read_permissions(vt015, role, path):
    assert vt015.client.get(path, headers=vt015.headers(role)).status_code == 200


@pytest.mark.parametrize("role", ["reviewer", "admin"])
def test_approval_permission_and_original_immutability(vt015, role):
    s = vt015
    response = s.client.post("/clusters/c1/approval", headers=s.headers(role))
    assert response.status_code == 201
    document = s.approvals.get("c1")
    assert document["approved_by"] == "reviewer-a"
    assert document["cluster_id"] == "c1"
    assert datetime.fromisoformat(document["approved_at"].replace("Z", "+00:00")).tzinfo is not None
    assert s.approvals.writes == 1
    read = s.client.get("/clusters/c1/approval", headers=s.headers(role))
    assert read.status_code == 200
    assert read.json() == document
    assert_original_untouched(s)


@pytest.mark.parametrize("invalid,expired", [(True, False), (False, True)])
def test_invalid_or_expired_jwt_before_storage(vt015, invalid, expired):
    s = vt015
    assert s.client.post("/clusters/c1/approval", headers=s.headers(invalid=invalid, expired=expired)).status_code == 401
    assert not s.logs.mock_calls and not s.clusters.mock_calls
    assert s.approvals.writes == 0


def test_duplicate_approval_preserves_winner(vt015):
    s = vt015
    first = s.client.post("/clusters/c1/approval", headers=s.headers())
    assert first.status_code == 201
    winner = s.approvals.get("c1")
    assert s.client.post("/clusters/c1/approval", headers=s.headers(actor="reviewer-b")).status_code == 409
    assert s.approvals.get("c1") == winner
    assert s.approvals.writes == 1


def test_two_concurrent_approvals_have_one_success_and_one_storage_write(vt015):
    s = vt015
    barrier = Barrier(2)

    def approve(actor):
        with TestClient(main.app) as client:
            barrier.wait(timeout=10)
            return client.post("/clusters/c1/approval", headers=s.headers(actor=actor)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve, ["reviewer-a", "reviewer-b"]))
    assert sorted(outcomes) == [201, 409]
    assert s.approvals.writes == 1
    assert len(s.approvals.documents) == 1
    assert s.approvals.get("c1")["approved_by"] in {"reviewer-a", "reviewer-b"}
    assert_original_untouched(s)


def test_missing_cluster_does_not_create_approval(vt015):
    s = vt015
    s.clusters.get_cluster.return_value = None
    response = s.client.post("/clusters/missing/approval", headers=s.headers())
    assert response.status_code == 404
    s.clusters.get_cluster.assert_called_once_with("missing")
    assert s.approvals.writes == 0


def test_storage_failure_is_503_without_write(vt015):
    s = vt015
    s.approvals.fail = True
    assert s.client.post("/clusters/c1/approval", headers=s.headers()).status_code == 503
    assert s.approvals.writes == 0
    assert_original_untouched(s)


@pytest.mark.parametrize("body", [{"approved_by": "admin"}, {"score": 0, "log_ids": []}])
def test_actor_spoofing_and_original_data_payload_are_rejected(vt015, body):
    s = vt015
    assert s.client.post("/clusters/c1/approval", headers=s.headers(), json=body).status_code == 422
    assert s.approvals.writes == 0
    assert_original_untouched(s)


@pytest.mark.parametrize("method,path", [("patch", "/clusters/c1"), ("put", "/clusters/c1"), ("delete", "/clusters/c1"), ("patch", "/search")])
def test_reviewer_cannot_modify_original_data(vt015, method, path):
    s = vt015
    assert s.client.request(method, path, headers=s.headers(), json={"score": 0}).status_code in {403, 405}
    assert_original_untouched(s)
