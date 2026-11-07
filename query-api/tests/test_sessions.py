"""Security behavior of HTTP auth and operator actions with real signing/password hashing."""

import importlib
import secrets
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from ingestion.src.storage import StorageError

auth_stack = importlib.import_module("query-api.tests.auth_stack").auth_stack
tokens = importlib.import_module("query-api.src.tokens")
sessions_module = importlib.import_module("query-api.src.sessions")
CSRF = {"X-CSRF-Protection": "1"}


@pytest.fixture()
def stack():
    with auth_stack() as state:
        state.repository.ensure_ready()
        state.repository.create_admin(**state.credentials)
        with TestClient(state.app, headers=CSRF) as client:
            state.http = client
            yield state


def login(stack):
    response = stack.http.post("/auth/login", json=stack.credentials)
    assert response.status_code == 200
    return response.json(), response.cookies["lae_refresh"]


def cookie(token):
    # Internal API path differs from the public proxy path to which the cookie is scoped.
    return {"Cookie": f"lae_refresh={token}"}


def bearer(access):
    return {"Authorization": f"Bearer {access['token']}"}


def test_login_cookie_and_stored_session_do_not_expose_refresh_token(stack):
    access, refresh = login(stack)
    claims = tokens.decode_access_token(access["token"])
    refresh_claims = tokens.decode_refresh_token(refresh)
    stored = stack.documents["auth-test-sessions", claims["sid"]]
    assert stored["refresh_hash"] == sessions_module.token_hash(refresh)
    assert refresh not in str(stored)
    assert claims["token_use"] == "access" and refresh_claims["token_use"] == "refresh"
    assert refresh_claims["exp"] - refresh_claims["iat"] == 604800
    response = stack.http.post("/auth/login", json=stack.credentials)
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Path=/api/auth" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    with pytest.raises(jwt.InvalidTokenError):
        tokens.decode_access_token(refresh)
    with pytest.raises(jwt.InvalidTokenError):
        tokens.decode_refresh_token(access["token"])


def test_rotation_preserves_absolute_expiry_and_reuse_revokes_whole_session(stack):
    access, old = login(stack)
    response = stack.http.post("/auth/refresh", headers=cookie(old))
    assert response.status_code == 200
    new = response.cookies["lae_refresh"]
    assert old != new
    assert tokens.decode_refresh_token(new)["exp"] == tokens.decode_refresh_token(old)["exp"]
    assert stack.http.get("/search", headers=bearer(access)).status_code == 200
    assert stack.http.post("/auth/refresh", headers=cookie(old)).status_code == 401
    assert stack.http.get("/search", headers=bearer(response.json())).status_code == 401
    assert stack.http.post("/auth/refresh", headers=cookie(new)).status_code == 401


def test_forged_refresh_cannot_revoke_a_known_session(stack):
    access, refresh = login(stack)
    claims = tokens.decode_refresh_token(refresh)
    forged = jwt.encode(claims, secrets.token_urlsafe(48), algorithm="HS256")
    assert stack.http.post("/auth/refresh", headers=cookie(forged)).status_code == 401
    assert stack.http.get("/search", headers=bearer(access)).status_code == 200


def test_logout_revokes_copied_access_but_preserves_other_browser(stack):
    first, refresh = login(stack)
    second, _ = login(stack)
    expired = jwt.encode({**tokens.decode_access_token(first["token"]), "exp": 1}, stack.secret, algorithm="HS256")
    headers = {**cookie(refresh), "Authorization": f"Bearer {expired}"}
    assert stack.http.post("/auth/logout", headers=headers).status_code == 204
    assert stack.http.post("/auth/logout", headers=headers).status_code == 204
    assert stack.http.get("/search", headers=bearer(first)).status_code == 401
    assert stack.http.get("/search", headers=bearer(second)).status_code == 200
    assert stack.http.post("/auth/refresh", headers=cookie(refresh)).status_code == 401


@pytest.mark.parametrize("action,value", [("disable", None), ("set-role", "viewer"),
    ("set-password", "new-test-password"), ("revoke-all", None), ("enable", None)])
def test_operator_change_revokes_every_session(stack, action, value):
    first, refresh = login(stack)
    second, _ = login(stack)
    stack.repository.administer(stack.credentials["username"], action, value=value)
    for access in (first, second):
        assert stack.http.get("/search", headers=bearer(access)).status_code == 401
    assert stack.http.post("/auth/refresh", headers=cookie(refresh)).status_code == 401
    if action == "disable":
        stack.repository.administer(stack.credentials["username"], "enable")
        assert stack.http.get("/search", headers=bearer(first)).status_code == 401


@pytest.mark.parametrize("path", ["/auth/login", "/auth/refresh", "/auth/logout"])
@pytest.mark.parametrize("origin", ["null", "https://evil.example"])
def test_auth_post_checks_origin_and_never_caches_errors(stack, path, origin):
    response = stack.http.post(path, json=stack.credentials, headers={"Origin": origin})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_auth_requires_csrf_header_even_without_origin(stack):
    with TestClient(stack.app) as client:
        assert client.post("/auth/login", json=stack.credentials).status_code == 403


def test_storage_failure_cannot_allow_access_refresh_or_report_logout(stack):
    access, refresh = login(stack)
    stack.client.get.side_effect = RuntimeError("private storage diagnostic")
    for response in (stack.http.get("/search", headers=bearer(access)),
                     stack.http.post("/auth/refresh", headers=cookie(refresh)),
                     stack.http.post("/auth/logout", headers=cookie(refresh))):
        assert response.status_code == 503
        assert "private storage diagnostic" not in response.text


def test_expired_access_signals_refresh_and_legacy_tokens_are_rejected(stack):
    access, _ = login(stack)
    claims = tokens.decode_access_token(access["token"])
    expired = jwt.encode({**claims, "exp": 1}, stack.secret, algorithm="HS256")
    response = stack.http.get("/search", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401 and response.headers["x-auth-reason"] == "access_expired"
    for key in ("sid", "ver", "token_use"):
        reduced = {k: v for k, v in claims.items() if k != key}
        token = jwt.encode(reduced, stack.secret, algorithm="HS256")
        assert stack.http.get("/search", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_expired_session_is_rejected_independently_of_cleanup(stack):
    access, refresh = login(stack)
    sid = tokens.decode_access_token(access["token"])["sid"]
    stack.documents["auth-test-sessions", sid]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert stack.http.get("/search", headers=bearer(access)).status_code == 401
    assert stack.http.post("/auth/refresh", headers=cookie(refresh)).status_code == 401


def test_concurrent_rotation_detects_replay_without_resurrecting_session(stack):
    _, refresh = login(stack)
    claims = tokens.decode_refresh_token(refresh)
    repository = stack.app.state.session_repository
    barrier = Barrier(2)
    original = repository._replace
    def simultaneous(sid, record, source):
        if source.get("revoked_at") is None:
            barrier.wait(timeout=5)
        return original(sid, record, source)
    def rotate():
        try:
            return repository.refresh(refresh, claims, stack.repository)
        except jwt.InvalidTokenError:
            return None
    with patch.object(repository, "_replace", simultaneous), ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    assert sum(result is not None for result in results) == 1
    with pytest.raises(jwt.InvalidTokenError):
        repository.validate(claims, stack.repository)


def test_logout_racing_rotation_cannot_be_overwritten(stack):
    _, refresh = login(stack)
    claims = tokens.decode_refresh_token(refresh)
    repository = stack.app.state.session_repository
    original = repository._replace
    with patch.object(repository, "_replace") as replace:
        def interleave(sid, record, source):
            if source.get("revoked_at") is None:
                with patch.object(repository, "_replace", original):
                    repository.revoke(sid)
            return original(sid, record, source)
        replace.side_effect = interleave
        with pytest.raises(jwt.InvalidTokenError):
            repository.refresh(refresh, claims, stack.repository)
    assert repository.get_record(claims["sid"])["_source"]["revoked_at"]


def test_production_cookie_is_secure_and_access_cannot_outlive_session(stack, monkeypatch):
    config = importlib.import_module("query-api.src.config")
    monkeypatch.setattr(config, "AUTH_COOKIE_SECURE", True)
    monkeypatch.setattr(config, "AUTH_REFRESH_TTL_SECONDS", 30)
    monkeypatch.setattr(config, "JWT_EXPIRY_SECONDS", 900)
    response = stack.http.post("/auth/login", json=stack.credentials)
    assert "Secure" in response.headers["set-cookie"]
    access = tokens.decode_access_token(response.json()["token"])
    refresh = tokens.decode_refresh_token(response.cookies["lae_refresh"])
    assert access["exp"] == refresh["exp"]


def test_corrupt_session_fails_closed_with_sanitized_service_error(stack):
    access, _ = login(stack)
    sid = tokens.decode_access_token(access["token"])["sid"]
    stack.documents["auth-test-sessions", sid]["expires_at"] = "invalid-private-value"
    response = stack.http.get("/search", headers=bearer(access))
    assert response.status_code == 503
    assert "invalid-private-value" not in response.text
