"""Login JSON va JWT; dung Argon2/PyJWT that, mock client OpenSearch."""

import importlib
import secrets
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import jwt
import pytest
from fastapi.testclient import TestClient
from opensearchpy.exceptions import NotFoundError
from starlette.datastructures import State

from ingestion.src.storage import OpenSearchLogStore

main = importlib.import_module("query-api.src.main")
auth = importlib.import_module("query-api.src.auth")
config = importlib.import_module("query-api.src.config")
tokens = importlib.import_module("query-api.src.tokens")
users = importlib.import_module("query-api.src.users")
passwords = importlib.import_module("query-api.src.passwords")


@pytest.fixture()
def jwt_config(monkeypatch):
    secret = secrets.token_urlsafe(48)
    monkeypatch.setattr(config, "JWT_SECRET", secret)
    monkeypatch.setattr(config, "JWT_EXPIRY_SECONDS", 3600)
    return secret


@pytest.fixture()
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(tokens, "datetime", Clock)
    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    return Clock


@pytest.fixture(scope="module")
def admin_credentials():
    password = secrets.token_urlsafe(32)
    return "test-admin", password, passwords.hash_password(password)


@pytest.fixture()
def login_app(monkeypatch, jwt_config, admin_credentials):
    username, password, hashed = admin_credentials
    document = {
        "username": username, "password_hash": hashed,
        "role": "admin", "created_at": "2026-01-01T00:00:00+00:00",
    }
    client = Mock()

    def get(*, index, id):
        if id != username:
            raise NotFoundError(404, "not_found")
        return {"found": True, "_source": document}

    client.get.side_effect = get
    monkeypatch.setattr(config, "USERS_INDEX", "login-test-users")
    repository = users.UserRepository(OpenSearchLogStore(client))
    monkeypatch.setattr(main.app, "state", State({"user_repository": repository}))
    with TestClient(main.app) as app:
        yield app, client, {"username": username, "password": password}, document


def test_login_returns_signed_admin_claims_and_configured_expiry(
    login_app, jwt_config, clock, monkeypatch, caplog
):
    app, storage, credentials, document = login_app
    original = deepcopy(document)
    monkeypatch.setattr(config, "JWT_EXPIRY_SECONDS", 120)

    response = app.post("/auth/login", json=credentials)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"token", "expires_at"}
    claims = jwt.decode(body["token"], jwt_config, algorithms=["HS256"])
    assert jwt.get_unverified_header(body["token"])["alg"] == "HS256"
    assert claims == {
        "sub": credentials["username"], "role": "admin",
        "exp": int((clock.current + timedelta(seconds=120)).timestamp()),
    }
    assert tokens.decode_access_token(body["token"]) == claims
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert expires_at.utcoffset() == timedelta(0)
    assert expires_at.timestamp() == claims["exp"]
    storage.get.assert_called_once_with(index="login-test-users", id=credentials["username"])
    storage.create.assert_not_called()
    storage.index.assert_not_called()
    storage.indices.create.assert_not_called()
    assert document == original
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    for sensitive in (jwt_config, credentials["password"], document["password_hash"], body["token"]):
        assert sensitive not in caplog.text


def test_wrong_username_and_password_have_identical_generic_response(login_app, monkeypatch):
    app, _, credentials, _ = login_app
    verify = Mock(wraps=auth.verify_password)
    monkeypatch.setattr(auth, "verify_password", verify)

    missing = app.post("/auth/login", json={**credentials, "username": "not-an-account"})
    wrong = app.post("/auth/login", json={**credentials, "password": secrets.token_urlsafe(32)})

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {"detail": "Invalid username or password"}
    assert verify.call_count == 2
    assert verify.call_args_list[0].args[1] == auth._DUMMY_HASH


@pytest.mark.parametrize("username", ["", " \t"])
def test_blank_username_is_invalid_credentials_without_storage_error(login_app, username):
    app, storage, credentials, _ = login_app

    response = app.post("/auth/login", json={**credentials, "username": username})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    storage.get.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [("role", "viewer"), ("username", "another-admin"), ("password_hash", "broken"),
     ("password_hash", None)],
)
def test_invalid_stored_account_cannot_login(login_app, field, value):
    app, _, credentials, document = login_app
    document[field] = value

    response = app.post("/auth/login", json=credentials)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}


@pytest.mark.parametrize("secret", [None, "", " \t", "too-short"])
def test_missing_or_weak_secret_disables_login_without_fallback(login_app, monkeypatch, secret, caplog):
    app, storage, credentials, _ = login_app
    monkeypatch.setattr(config, "JWT_SECRET", secret)

    response = app.post("/auth/login", json=credentials)

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication unavailable"}
    storage.get.assert_not_called()
    assert credentials["password"] not in caplog.text
    if secret and secret.strip():
        assert secret not in response.text + caplog.text


@pytest.mark.parametrize("lifetime", [0, -1, "3600", True, None])
def test_invalid_expiry_configuration_disables_login(login_app, monkeypatch, lifetime):
    app, storage, credentials, _ = login_app
    monkeypatch.setattr(config, "JWT_EXPIRY_SECONDS", lifetime)

    response = app.post("/auth/login", json=credentials)

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication unavailable"}
    storage.get.assert_not_called()


def test_overflowing_expiry_cannot_issue_a_token(login_app, monkeypatch):
    app, _, credentials, _ = login_app
    monkeypatch.setattr(config, "JWT_EXPIRY_SECONDS", 10**30)

    response = app.post("/auth/login", json=credentials)

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication unavailable"}


def test_storage_failure_returns_sanitized_503(login_app, jwt_config, caplog):
    app, storage, credentials, _ = login_app
    storage.get.side_effect = RuntimeError(jwt_config + credentials["password"])

    response = app.post("/auth/login", json=credentials)

    assert response.status_code == 503
    assert response.json() == {"detail": "User storage unavailable"}
    assert jwt_config not in response.text + caplog.text
    assert credentials["password"] not in response.text + caplog.text


def test_unavailable_repository_returns_503(login_app):
    app, _, credentials, _ = login_app
    main.app.state.user_repository = None

    assert app.post("/auth/login", json=credentials).status_code == 503


def test_password_is_masked_in_request_model_repr(admin_credentials):
    username, password, _ = admin_credentials

    assert password not in repr(auth.LoginRequest(username=username, password=password))


@pytest.mark.parametrize("missing", ["username", "password"])
def test_login_requires_both_json_fields(login_app, missing):
    app, storage, credentials, _ = login_app
    body = {key: value for key, value in credentials.items() if key != missing}

    assert app.post("/auth/login", json=body).status_code == 422
    storage.get.assert_not_called()


@pytest.mark.parametrize("invalid", ["missing_username", "wrong_username_type", "invalid_json"])
def test_validation_errors_never_echo_passwords(login_app, invalid, caplog):
    app, storage, credentials, _ = login_app
    if invalid == "invalid_json":
        response = app.post("/auth/login", content='{"password":"' + credentials["password"],
                            headers={"Content-Type": "application/json"})
    else:
        body = {"password": credentials["password"]}
        if invalid == "wrong_username_type":
            body["username"] = 123
        response = app.post("/auth/login", json=body)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid login request"}
    assert credentials["password"] not in response.text + caplog.text
    storage.get.assert_not_called()


def test_browser_preflight_allows_json_login(login_app):
    app, _, _, _ = login_app

    response = app.options("/auth/login", headers={
        "Origin": "https://frontend.example",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })

    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]


def test_health_and_login_remain_public_while_search_requires_token(login_app):
    app, _, credentials, _ = login_app

    # Bearer khong hop le cung khong duoc chan cac route public.
    invalid_header = {"Authorization": "Bearer invalid"}
    assert app.get("/health").status_code == 200
    assert app.get("/health", headers=invalid_header).status_code == 200
    login = app.post("/auth/login", json=credentials, headers=invalid_header)
    assert login.status_code == 200
    assert app.get("/search").status_code == 401
    assert app.get("/search", headers={
        "Authorization": f"Bearer {login.json()['token']}"
    }).status_code == 200


@pytest.mark.parametrize("path", ["/auth/register", "/auth/signup", "/auth/reset-password"])
def test_no_registration_or_password_reset_route(login_app, path):
    app, _, credentials, _ = login_app

    assert app.post(path, json=credentials).status_code == 404


def test_issued_token_expires_at_exact_configured_boundary(jwt_config, clock):
    body = tokens.create_access_token("test-admin")
    clock.current += timedelta(seconds=config.JWT_EXPIRY_SECONDS - 1)
    assert tokens.decode_access_token(body["token"])["sub"] == "test-admin"

    clock.current += timedelta(seconds=1)

    with pytest.raises(jwt.ExpiredSignatureError):
        tokens.decode_access_token(body["token"])


@pytest.mark.parametrize("algorithm", ["none", "HS384", "HS512"])
def test_unapproved_algorithms_are_rejected(jwt_config, clock, algorithm):
    token = jwt.encode(
        {"sub": "test-admin", "role": "admin", "exp": int(clock.current.timestamp()) + 3600},
        "" if algorithm == "none" else jwt_config, algorithm=algorithm,
    )

    with pytest.raises(jwt.InvalidAlgorithmError):
        tokens.decode_access_token(token)


def test_wrong_signature_is_rejected(jwt_config, clock):
    token = jwt.encode(
        {"sub": "test-admin", "role": "admin", "exp": int(clock.current.timestamp()) + 3600},
        secrets.token_urlsafe(48), algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidSignatureError):
        tokens.decode_access_token(token)


@pytest.mark.parametrize("missing", ["sub", "role", "exp"])
def test_required_claims_cannot_be_omitted(jwt_config, clock, missing):
    claims = {"sub": "test-admin", "role": "admin", "exp": int(clock.current.timestamp()) + 3600}
    del claims[missing]
    token = jwt.encode(claims, jwt_config, algorithm="HS256")

    with pytest.raises(jwt.MissingRequiredClaimError):
        tokens.decode_access_token(token)


@pytest.mark.parametrize(
    ("claim", "value"),
    [("sub", ""), ("sub", 42), ("role", "viewer"), ("role", None), ("exp", "2000000000")],
)
def test_invalid_admin_claims_are_rejected(jwt_config, clock, claim, value):
    claims = {"sub": "test-admin", "role": "admin", "exp": int(clock.current.timestamp()) + 3600}
    claims[claim] = value
    token = jwt.encode(claims, jwt_config, algorithm="HS256")

    with pytest.raises(jwt.InvalidTokenError):
        tokens.decode_access_token(token)


def test_validator_also_requires_configured_secret(jwt_config, monkeypatch):
    token = tokens.create_access_token("test-admin")["token"]
    monkeypatch.setattr(config, "JWT_SECRET", None)

    with pytest.raises(tokens.JWTConfigurationError):
        tokens.decode_access_token(token)
