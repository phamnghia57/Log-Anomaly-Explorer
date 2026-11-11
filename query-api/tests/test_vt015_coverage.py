"""Close approval error-path and token-input gaps found by branch coverage."""
import importlib
from unittest.mock import Mock

import jwt
import pytest
from fastapi.testclient import TestClient

from ingestion.src.storage import StorageError

main = importlib.import_module("query-api.src.main")
tokens = importlib.import_module("query-api.src.tokens")
config = importlib.import_module("query-api.src.config")
ApprovalRepository = importlib.import_module("query-api.src.approvals").ApprovalRepository


@pytest.fixture
def approval_api(monkeypatch, admin_auth):
    clusters, approvals = Mock(), Mock()
    clusters.get_cluster.return_value = {"cluster_id": "c1"}
    monkeypatch.setattr(main, "cluster_store", clusters)
    monkeypatch.setitem(main.app.state._state, "approval_repository", approvals)
    headers = {"Authorization": "Bearer " + tokens.create_access_token("reviewer-a", "reviewer")["token"]}
    with TestClient(main.app) as client:
        yield client, headers, clusters, approvals


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_approval_rejects_missing_auth_before_storage(approval_api, method):
    client, _, clusters, approvals = approval_api
    assert client.request(method, "/clusters/c1/approval").status_code == 401
    assert not clusters.mock_calls and not approvals.mock_calls


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_unavailable_approval_repository_is_503(approval_api, monkeypatch, method):
    client, headers, _, _ = approval_api
    monkeypatch.setitem(main.app.state._state, "approval_repository", None)
    assert client.request(method, "/clusters/c1/approval", headers=headers).status_code == 503


def test_missing_cluster_on_approval_read_does_not_access_repository(approval_api):
    client, headers, clusters, approvals = approval_api
    clusters.get_cluster.return_value = None
    assert client.get("/clusters/missing/approval", headers=headers).status_code == 404
    assert not approvals.mock_calls


def test_missing_approval_and_failed_read_are_distinct(approval_api):
    client, headers, _, approvals = approval_api
    approvals.get.return_value = None
    assert client.get("/clusters/c1/approval", headers=headers).status_code == 404
    approvals.get.side_effect = StorageError("test read failure")
    assert client.get("/clusters/c1/approval", headers=headers).status_code == 503


def test_production_repository_reads_document_and_found_false():
    client = Mock()
    repository = ApprovalRepository(type("Store", (), {"client": client})())
    document = {"cluster_id": "c1", "approved_by": "reviewer-a"}
    client.get.return_value = {"found": True, "_source": document}
    assert repository.get("c1") == document
    client.get.assert_called_with(index="cluster-approvals", id="c1")
    client.get.return_value = {"found": False}
    assert repository.get("c1") is None


def test_token_issuer_rejects_unsupported_role(admin_auth):
    with pytest.raises(ValueError, match="Unsupported role"):
        tokens.create_access_token("someone", "viewer")


@pytest.mark.parametrize("expiry", [[], float("inf")], ids=["non-numeric", "non-finite"])
def test_malformed_expiry_is_invalid_token(admin_auth, expiry):
    token = jwt.encode({"sub": "reviewer-a", "role": "reviewer", "exp": expiry},
                       config.JWT_SECRET, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        tokens.decode_access_token(token)
