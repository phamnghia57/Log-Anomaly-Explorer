"""Explicit setup and login integration with a stateful OpenSearch client double."""
import importlib
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from jsonschema import validate
from opensearchpy.exceptions import ConflictError, NotFoundError, RequestError

from ingestion.src.storage import InMemoryLogStore, OpenSearchLogStore, StorageError

setup = importlib.import_module("query-api.src.setup_reviewer")
users = importlib.import_module("query-api.src.users")
approvals = importlib.import_module("query-api.src.approvals")
config = importlib.import_module("query-api.src.config")
passwords = importlib.import_module("query-api.src.passwords")


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setenv("REVIEWER_SEED_USERNAME", "submission-reviewer")
    monkeypatch.setenv("REVIEWER_SEED_PASSWORD", "test-reviewer-password")
    monkeypatch.setattr(config, "USERS_INDEX", "vt015-setup-users")
    client, documents, indexes = Mock(), {}, set()
    client.indices.exists.side_effect = lambda *, index: index in indexes

    def create_index(*, index, body):
        indexes.add(index)
        return {"acknowledged": True}

    def get(*, index, id):
        if (index, id) not in documents:
            raise NotFoundError(404, "not_found")
        return {"found": True, "_source": deepcopy(documents[index, id])}

    def create(*, index, id, body, refresh):
        if (index, id) in documents:
            raise ConflictError(409, "version_conflict_engine_exception")
        documents[index, id] = deepcopy(body)
        return {"result": "created"}

    client.indices.create.side_effect = create_index
    client.get.side_effect = get
    client.create.side_effect = create
    store = OpenSearchLogStore(client, shards=1, replicas=0)
    monkeypatch.setattr(store, "ensure_ready", Mock(side_effect=AssertionError("original indexes")))
    return store, client, documents, indexes


def test_setup_creates_hashed_schema_valid_reviewer_and_only_required_indexes(backend, monkeypatch):
    store, client, documents, indexes = backend
    monkeypatch.setattr(config, "JWT_SECRET", None)
    assert setup.setup_reviewer(store) is True
    assert indexes == {"vt015-setup-users", "cluster-approvals"}
    document = documents["vt015-setup-users", "submission-reviewer"]
    schema = json.loads((Path(__file__).parents[2] / "docs/architect/contracts/users-schema.json").read_text())
    validate(document, schema)
    assert document["role"] == "reviewer"
    assert passwords.verify_password("test-reviewer-password", document["password_hash"])
    assert "test-reviewer-password" not in json.dumps(document)
    mapping = client.indices.create.call_args.kwargs["body"]["mappings"]
    assert mapping["dynamic"] == "strict"
    assert set(mapping["properties"]) == {"cluster_id", "approved_by", "approved_at"}
    assert client.create.call_args.kwargs["refresh"] == "wait_for"
    client.index.assert_not_called()
    client.update.assert_not_called()
    client.delete.assert_not_called()


def test_provisioned_account_can_login_as_reviewer(backend, monkeypatch, admin_auth):
    store, _, _, _ = backend
    assert setup.setup_reviewer(store)
    main = importlib.import_module("query-api.src.main")
    tokens = importlib.import_module("query-api.src.tokens")
    monkeypatch.setitem(main.app.state._state, "user_repository", users.UserRepository(store))
    with TestClient(main.app) as client:
        response = client.post("/auth/login", json={
            "username": "submission-reviewer", "password": "test-reviewer-password",
        })
    assert response.status_code == 200
    claims = tokens.decode_access_token(response.json()["token"])
    assert claims["sub"] == "submission-reviewer" and claims["role"] == "reviewer"


@pytest.mark.parametrize("role", ["admin", "reviewer"])
def test_setup_preserves_existing_account_and_never_rehashes(backend, monkeypatch, role):
    store, client, documents, _ = backend
    key = "vt015-setup-users", "submission-reviewer"
    original = {"username": key[1], "role": role, "password_hash": "existing"}
    documents[key] = deepcopy(original)
    monkeypatch.setattr(users, "hash_password", Mock(side_effect=AssertionError("must not rehash")))
    assert setup.setup_reviewer(store) is False
    assert documents[key] == original
    client.create.assert_not_called()


def test_repeated_setup_preserves_password_and_index_mappings(backend):
    store, client, documents, _ = backend
    assert setup.setup_reviewer(store)
    original = deepcopy(documents)
    assert not setup.setup_reviewer(store)
    assert documents == original
    assert client.indices.create.call_count == 2
    assert client.create.call_count == 1
    client.indices.put_mapping.assert_not_called()


def test_reviewer_create_loses_race_without_overwriting(backend):
    store, client, documents, _ = backend
    original = {"role": "admin", "password_hash": "winner"}

    def other_process_wins(**kwargs):
        documents[kwargs["index"], kwargs["id"]] = deepcopy(original)
        raise ConflictError(409, "version_conflict_engine_exception")

    client.create.side_effect = other_process_wins
    assert setup.setup_reviewer(store) is False
    assert list(documents.values()) == [original]


@pytest.mark.parametrize("name", ["REVIEWER_SEED_USERNAME", "REVIEWER_SEED_PASSWORD"])
@pytest.mark.parametrize("value", ["", "   "])
def test_invalid_credentials_fail_before_connecting(backend, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    factory = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(setup, "build_store", factory)
    with pytest.raises(ValueError):
        setup.setup_reviewer()
    factory.assert_not_called()


def test_setup_requires_opensearch_backend(backend):
    with pytest.raises(ValueError, match="opensearch"):
        setup.setup_reviewer(InMemoryLogStore())


@pytest.mark.parametrize("failure", ["unacknowledged", "timeout", "request_error"])
def test_index_failure_does_not_provision_reviewer(backend, failure):
    store, client, documents, indexes = backend
    indexes.add("vt015-setup-users")
    client.indices.create.side_effect = None
    client.indices.create.return_value = {"acknowledged": False}
    if failure == "timeout":
        client.indices.create.side_effect = TimeoutError("test detail")
    elif failure == "request_error":
        client.indices.create.side_effect = RequestError(400, "invalid_mapping")
    with pytest.raises(StorageError, match="cannot prepare approval index"):
        setup.setup_reviewer(store)
    assert not documents
    client.create.assert_not_called()


def test_concurrent_index_creator_is_benign(backend):
    store, client, _, indexes = backend
    indexes.add("vt015-setup-users")
    client.indices.create.side_effect = RequestError(400, "resource_already_exists_exception")
    assert setup.setup_reviewer(store)


@pytest.mark.parametrize("result,error", [({}, None), (None, TimeoutError("secret-detail"))])
def test_unconfirmed_reviewer_creation_fails_without_sensitive_details(backend, result, error):
    store, client, _, _ = backend
    client.create.side_effect = error
    client.create.return_value = result
    with pytest.raises(StorageError, match="^cannot create reviewer$"):
        setup.setup_reviewer(store)


@pytest.mark.parametrize("failed", [False, True])
def test_owned_connection_is_closed_on_success_and_failure(backend, monkeypatch, failed):
    store, client, _, _ = backend
    monkeypatch.setattr(setup, "build_store", lambda: store)
    if failed:
        client.indices.exists.side_effect = TimeoutError()
        with pytest.raises(StorageError):
            setup.setup_reviewer()
    else:
        assert setup.setup_reviewer()
    client.close.assert_called_once()


def test_borrowed_connection_is_not_closed(backend):
    store, client, _, _ = backend
    setup.setup_reviewer(store)
    client.close.assert_not_called()


def test_connection_failure_is_sanitized(backend, monkeypatch):
    monkeypatch.setattr(setup, "build_store", Mock(side_effect=RuntimeError("secret-detail")))
    with pytest.raises(StorageError, match="^cannot connect to reviewer storage$"):
        setup.setup_reviewer()


@pytest.mark.parametrize("outcome", [True, False, StorageError("secret-detail")])
def test_cli_reports_outcome_without_credentials(monkeypatch, capsys, outcome):
    action = Mock()
    if isinstance(outcome, Exception):
        action.side_effect = outcome
    else:
        action.return_value = outcome
    monkeypatch.setattr(setup, "setup_reviewer", action)
    assert setup.main() == (1 if isinstance(outcome, Exception) else 0)
    captured = capsys.readouterr()
    assert "secret-detail" not in captured.out + captured.err
    if outcome is False:
        assert "existing account preserved" in captured.out
