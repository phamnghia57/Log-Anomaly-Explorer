"""Supplemental GREEN checks; the committed RED suite remains unchanged."""
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from opensearchpy.exceptions import ConflictError, NotFoundError

from ingestion.src.storage import StorageError

main = importlib.import_module("query-api.src.main")
tokens = importlib.import_module("query-api.src.tokens")
passwords = importlib.import_module("query-api.src.passwords")
ApprovalRepository = importlib.import_module("query-api.src.approvals").ApprovalRepository


def test_reviewer_login_and_assistant_denial(monkeypatch, admin_auth):
    # Patch State's backing mapping so teardown restores keys rather than deleting them.
    repository = Mock()
    repository.get.return_value = {
        "username": "reviewer-a", "role": "reviewer",
        "password_hash": passwords.hash_password("reviewer-password"),
    }
    monkeypatch.setitem(main.app.state._state, "user_repository", repository)
    conversations = Mock()
    monkeypatch.setitem(main.app.state._state, "assistant_conversations", conversations)
    with TestClient(main.app) as client:
        response = client.post("/auth/login", json={
            "username": "reviewer-a", "password": "reviewer-password",
        })
        assert response.status_code == 200
        token = response.json()["token"]
        assert tokens.decode_access_token(token)["role"] == "reviewer"
        headers = {"Authorization": f"Bearer {token}"}
        for method, path in [
            ("GET", "/assistant/clusters/c1/conversation"),
            ("POST", "/assistant/clusters/c1/conversation/messages"),
        ]:
            assert client.request(method, path, headers=headers, json={}).status_code == 403
    assert not conversations.mock_calls


def test_repository_uses_separate_index_and_create_only():
    client = Mock()
    client.create.return_value = {"result": "created"}
    repository = ApprovalRepository(SimpleNamespace(client=client))
    document = {"cluster_id": "c1", "approved_by": "reviewer-a", "approved_at": "now"}
    assert repository.create(document) is True
    client.create.assert_called_once_with(
        index="cluster-approvals", id="c1", body=document, refresh="wait_for",
    )
    assert not client.index.called and not client.update.called
    client.create.side_effect = ConflictError(409, "version_conflict_engine_exception")
    assert repository.create(document) is False


@pytest.mark.parametrize("result,error", [({}, None), (None, TimeoutError())])
def test_repository_never_reports_unconfirmed_write_as_success(result, error):
    client = Mock()
    client.create.return_value = result
    client.create.side_effect = error
    with pytest.raises(StorageError):
        ApprovalRepository(SimpleNamespace(client=client)).create({"cluster_id": "c1"})


def test_repository_read_distinguishes_missing_document_and_storage_failure():
    client = Mock()
    repository = ApprovalRepository(SimpleNamespace(client=client))
    client.get.side_effect = NotFoundError(404, "not_found")
    assert repository.get("c1") is None
    for error in [NotFoundError(404, "index_not_found_exception"), TimeoutError()]:
        client.get.side_effect = error
        with pytest.raises(StorageError):
            repository.get("c1")
