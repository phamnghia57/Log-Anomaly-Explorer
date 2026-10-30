"""Password hashing, users repository va seed CLI; OpenSearch duoc mock."""

import importlib
import json
import os
import secrets
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from argon2 import extract_parameters
from argon2.exceptions import HashingError
from argon2.low_level import Type
from jsonschema import FormatChecker, validate
from opensearchpy.exceptions import ConflictError, NotFoundError, RequestError

from ingestion.src.storage import InMemoryLogStore, OpenSearchLogStore, StorageError

config = importlib.import_module("query-api.src.config")
passwords = importlib.import_module("query-api.src.passwords")
users = importlib.import_module("query-api.src.users")
seed = importlib.import_module("query-api.src.seed_admin")


@pytest.fixture()
def credentials(monkeypatch):
    password = secrets.token_urlsafe(32)
    monkeypatch.setattr(config, "ADMIN_SEED_USERNAME", "test-admin")
    monkeypatch.setattr(config, "ADMIN_SEED_PASSWORD", password)
    monkeypatch.setattr(config, "JWT_SECRET", None)
    return "test-admin", password


@pytest.fixture()
def repository(monkeypatch):
    documents = {}
    client = Mock()
    client.indices.exists.return_value = False
    client.indices.create.return_value = {"acknowledged": True}

    def get(*, index, id):
        if id not in documents:
            raise NotFoundError(404, "not_found", {"found": False})
        return {"found": True, "_source": deepcopy(documents[id])}

    def create(*, index, id, body, refresh):
        if id in documents:
            raise ConflictError(409, "version_conflict_engine_exception")
        documents[id] = deepcopy(body)
        return {"result": "created"}

    client.get.side_effect = get
    client.create.side_effect = create
    monkeypatch.setattr(config, "USERS_INDEX", "test-users")
    log_store = OpenSearchLogStore(client, shards=2, replicas=1)
    return users.UserRepository(log_store), client, documents


def test_argon2_hashes_are_salted_and_verify_exact_password():
    password = secrets.token_urlsafe(32)
    first, second = passwords.hash_password(password), passwords.hash_password(password)

    assert first != second
    assert first != password
    assert extract_parameters(first).type == Type.ID
    assert passwords.verify_password(password, first)
    assert not passwords.verify_password(password + "x", first)


def test_unicode_and_long_passwords_are_not_truncated():
    password = "mật khẩu " + secrets.token_urlsafe(80)
    hashed = passwords.hash_password(password)

    assert passwords.verify_password(password, hashed)
    assert not passwords.verify_password(password[:72], hashed)


@pytest.mark.parametrize("hashed", ["", "invalid-hash", "$argon2id$broken"])
def test_invalid_hash_fails_closed(hashed):
    assert not passwords.verify_password(secrets.token_urlsafe(32), hashed)


@pytest.mark.parametrize("password", ["", " ", "\t\n"])
def test_empty_password_is_not_hashed(password):
    with pytest.raises(ValueError, match="Password must not be empty"):
        passwords.hash_password(password)


def test_seed_creates_schema_valid_admin_in_users_only(repository, credentials, caplog):
    repo, client, documents = repository
    username, password = credentials

    assert seed.seed_admin(repo) is True

    body = documents[username]
    schema = json.loads(
        (Path(__file__).parents[2] / "docs/architect/contracts/users-schema.json").read_text()
    )
    validate(body, schema, format_checker=FormatChecker())
    assert set(body) == {"username", "password_hash", "role", "created_at"}
    assert body["username"] == username
    assert body["role"] == "admin"
    assert datetime.fromisoformat(body["created_at"]).utcoffset().total_seconds() == 0
    assert passwords.verify_password(password, body["password_hash"])
    assert password not in json.dumps(body)
    client.create.assert_called_once_with(
        index="test-users", id=username, body=body, refresh="wait_for"
    )
    client.index.assert_not_called()
    mapping = client.indices.create.call_args.kwargs["body"]
    assert client.indices.create.call_args.kwargs["index"] == "test-users"
    assert mapping["settings"]["index"] == {"number_of_shards": 2, "number_of_replicas": 1}
    assert mapping["mappings"]["dynamic"] == "strict"
    assert set(mapping["mappings"]["properties"]) == set(schema["properties"])
    assert mapping["mappings"]["properties"]["password_hash"]["index"] is False
    assert password not in caplog.text


def test_repeated_seed_does_not_rehash_or_update(repository, credentials, monkeypatch):
    repo, client, documents = repository
    username, _ = credentials
    assert seed.seed_admin(repo) is True
    original = deepcopy(documents[username])
    client.indices.exists.return_value = True
    monkeypatch.setattr(users, "hash_password", Mock(side_effect=AssertionError("must not rehash")))

    assert seed.seed_admin(repo) is False

    assert documents[username] == original
    assert client.create.call_count == 1
    assert client.indices.create.call_count == 1


def test_existing_account_is_preserved_with_different_seed_password(repository, credentials):
    repo, client, documents = repository
    username, seed_password = credentials
    old_password = secrets.token_urlsafe(32)
    original = {
        "username": username, "password_hash": passwords.hash_password(old_password),
        "role": "admin", "created_at": "2026-01-01T00:00:00+00:00",
        "last_login_at": "2026-01-02T00:00:00+00:00",
    }
    documents[username] = deepcopy(original)

    assert seed.seed_admin(repo) is False

    assert documents[username] == original
    assert passwords.verify_password(old_password, documents[username]["password_hash"])
    assert not passwords.verify_password(seed_password, documents[username]["password_hash"])
    client.create.assert_not_called()


def test_concurrent_seed_preserves_winning_account(repository, credentials):
    repo, client, documents = repository
    username, _ = credentials
    winning_hash = passwords.hash_password(secrets.token_urlsafe(32))

    def concurrent_create(**kwargs):
        documents[username] = {**kwargs["body"], "password_hash": winning_hash}
        raise ConflictError(409, "version_conflict_engine_exception")

    client.create.side_effect = concurrent_create

    assert seed.seed_admin(repo) is False
    assert documents[username]["password_hash"] == winning_hash
    client.index.assert_not_called()


def test_concurrent_index_creation_is_safe(repository):
    repo, client, _ = repository
    client.indices.create.side_effect = RequestError(400, "resource_already_exists_exception")

    repo.ensure_ready()


@pytest.mark.parametrize("name", ["ADMIN_SEED_USERNAME", "ADMIN_SEED_PASSWORD"])
@pytest.mark.parametrize("value", [None, "", " \t"])
def test_missing_credentials_fail_before_any_storage_access(monkeypatch, credentials, name, value):
    monkeypatch.setattr(config, name, value)
    factory = Mock()
    monkeypatch.setattr(seed, "UserRepository", factory)

    with pytest.raises(ValueError, match=name):
        seed.seed_admin()

    factory.assert_not_called()


@pytest.mark.parametrize("operation", ["exists", "index_create", "get", "create"])
def test_opensearch_failures_stop_seed_without_leaking_details(repository, credentials, operation):
    repo, client, documents = repository
    _, password = credentials
    operations = {
        "exists": client.indices.exists, "index_create": client.indices.create,
        "get": client.get, "create": client.create,
    }
    operations[operation].side_effect = RuntimeError(password)

    with pytest.raises(StorageError) as error:
        seed.seed_admin(repo)

    assert password not in str(error.value)
    assert error.value.__suppress_context__
    assert not documents


def test_non_race_index_error_is_not_ignored(repository):
    repo, client, _ = repository
    client.indices.create.side_effect = RequestError(400, "mapper_parsing_exception")

    with pytest.raises(StorageError):
        repo.ensure_ready()


def test_unacknowledged_index_creation_stops_seed(repository, credentials):
    repo, client, _ = repository
    client.indices.create.return_value = {"acknowledged": False}

    with pytest.raises(StorageError):
        seed.seed_admin(repo)

    client.create.assert_not_called()


def test_missing_index_is_not_treated_as_missing_account(repository):
    repo, client, _ = repository
    client.get.side_effect = NotFoundError(404, "index_not_found_exception")

    with pytest.raises(StorageError):
        repo.get("test-admin")


def test_repository_uses_existing_storage_factory(repository, monkeypatch):
    repo, client, _ = repository
    factory = Mock(return_value=repo.log_store)
    monkeypatch.setattr(users, "build_store", factory)

    created = users.UserRepository()

    factory.assert_called_once_with()
    assert created.client is client


def test_memory_backend_is_rejected():
    with pytest.raises(ValueError, match="STORAGE_BACKEND=opensearch"):
        users.UserRepository(InMemoryLogStore())


def test_connection_factory_errors_are_sanitized(monkeypatch):
    secret = secrets.token_urlsafe(32)
    monkeypatch.setattr(users, "build_store", Mock(side_effect=RuntimeError(secret)))

    with pytest.raises(StorageError) as error:
        users.UserRepository()

    assert secret not in str(error.value)


@pytest.mark.parametrize("failure", [False, True])
def test_seed_closes_owned_client_even_on_failure(repository, credentials, monkeypatch, failure):
    repo, client, _ = repository
    monkeypatch.setattr(seed, "UserRepository", Mock(return_value=repo))
    if failure:
        client.indices.exists.side_effect = RuntimeError("unavailable")
        with pytest.raises(StorageError):
            seed.seed_admin()
    else:
        assert seed.seed_admin() is True
    client.close.assert_called_once_with()


def test_cli_is_idempotent_and_does_not_print_credentials(repository, credentials, monkeypatch, capsys):
    repo, _, _ = repository
    monkeypatch.setattr(seed, "UserRepository", Mock(return_value=repo))

    assert seed.main() == 0
    assert seed.main() == 0

    output = capsys.readouterr()
    assert "Admin created." in output.out
    assert "Existing account preserved" in output.out
    assert not output.err
    assert credentials[1] not in output.out


@pytest.mark.parametrize("failure", [ValueError, StorageError, HashingError])
def test_cli_reports_failure_without_secret_or_traceback(monkeypatch, capsys, failure):
    password = secrets.token_urlsafe(32)
    monkeypatch.setattr(seed, "seed_admin", Mock(side_effect=failure(password)))

    assert seed.main() == 1

    output = capsys.readouterr()
    assert "Admin seeding failed" in output.err
    assert password not in output.err + output.out
    assert "Traceback" not in output.err


def test_module_command_requires_credentials_before_connecting():
    env = os.environ.copy()
    for name in (
        "ADMIN_SEED_USERNAME", "ADMIN_SEED_PASSWORD", "JWT_SECRET",
        "JWT_EXPIRY_SECONDS", "USERS_INDEX",
    ):
        env.pop(name, None)
    env["STORAGE_BACKEND"] = "opensearch"

    result = subprocess.run(
        [sys.executable, "-m", "query-api.src.seed_admin"],
        cwd=Path(__file__).parents[2], env=env,
        capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == 1
    assert "ADMIN_SEED_USERNAME" in result.stderr
    assert "ADMIN_SEED_PASSWORD" in result.stderr
    assert not result.stdout
    assert "Traceback" not in result.stderr
