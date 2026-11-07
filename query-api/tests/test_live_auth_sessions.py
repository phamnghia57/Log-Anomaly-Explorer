"""Run explicitly with AUTH_TEST_OPENSEARCH_URL against an isolated test cluster."""

import importlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import jwt
import pytest
from opensearchpy import OpenSearch
from ingestion.src.storage import OpenSearchLogStore

config = importlib.import_module("query-api.src.config")
users_module = importlib.import_module("query-api.src.users")
sessions_module = importlib.import_module("query-api.src.sessions")
tokens = importlib.import_module("query-api.src.tokens")
pytestmark = pytest.mark.skipif(not os.environ.get("AUTH_TEST_OPENSEARCH_URL"),
                                reason="AUTH_TEST_OPENSEARCH_URL is required for live storage tests")


@pytest.fixture()
def live(monkeypatch):
    prefix = "issue73-test-" + secrets.token_hex(8)
    client = OpenSearch(os.environ["AUTH_TEST_OPENSEARCH_URL"], timeout=10, max_retries=0)
    monkeypatch.setattr(config, "JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setattr(config, "USERS_INDEX", prefix + "-users")
    monkeypatch.setattr(config, "AUTH_SESSIONS_INDEX", prefix + "-sessions")
    store = OpenSearchLogStore(client, shards=1, replicas=0)
    users = users_module.UserRepository(store)
    sessions = sessions_module.SessionRepository(store)
    users.ensure_ready()
    users.ensure_ready()  # migration is idempotent against real mappings
    sessions.ensure_ready()
    sessions.ensure_ready()
    users.create_admin("test-admin", secrets.token_urlsafe(32))
    user = users.get("test-admin")
    try:
        yield users, sessions, user, client, store
    finally:
        # Only this fixture's explicitly named random indexes are deleted.
        for index in (prefix + "-users", prefix + "-sessions"):
            client.indices.delete(index=index, ignore=[404])
        client.close()


def test_session_persists_across_repository_restart_and_realtime_revoke(live):
    users, sessions, user, client, store = live
    access, refresh, _ = sessions.start(user)
    claims = tokens.decode_access_token(access["token"])
    second_client = OpenSearch(os.environ["AUTH_TEST_OPENSEARCH_URL"], timeout=10, max_retries=0)
    try:
        restarted = sessions_module.SessionRepository(OpenSearchLogStore(second_client))
        restarted.validate(claims, users)
        restarted.revoke(claims["sid"])
        with pytest.raises(jwt.InvalidTokenError):
            sessions.validate(claims, users)
        assert sessions.get_record(claims["sid"])["_source"]["refresh_hash"] != refresh
    finally:
        second_client.close()


def test_real_compare_and_swap_serializes_competing_api_instances(live):
    users, sessions, user, _, store = live
    _, refresh, _ = sessions.start(user)
    claims = tokens.decode_refresh_token(refresh)
    barrier = Barrier(2)
    instances = [sessions_module.SessionRepository(store) for _ in range(2)]
    for instance in instances:
        original = instance.get_record
        first = [True]
        def read(sid, original=original, first=first):
            record = original(sid)
            if first[0]:
                first[0] = False
                barrier.wait(timeout=10)
            return record
        instance.get_record = read
    def rotate(instance):
        try:
            return instance.refresh(refresh, claims, users)
        except jwt.InvalidTokenError:
            return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(rotate, instances))
    assert sum(result is not None for result in results) == 1
    with pytest.raises(jwt.InvalidTokenError):
        sessions.validate(claims, users)


def test_real_logout_wins_against_inflight_rotation(live):
    users, sessions, user, _, store = live
    _, refresh, _ = sessions.start(user)
    claims = tokens.decode_refresh_token(refresh)
    other = sessions_module.SessionRepository(store)
    original = sessions._replace
    def interleave(sid, record, source):
        if not source.get("revoked_at"):
            other.revoke(sid)
        return original(sid, record, source)
    sessions._replace = interleave
    with pytest.raises(jwt.InvalidTokenError):
        sessions.refresh(refresh, claims, users)
    with pytest.raises(jwt.InvalidTokenError):
        other.validate(claims, users)


def test_real_account_update_revokes_all_sessions_and_enable_does_not_restore(live):
    users, sessions, user, _, _ = live
    access, refresh, _ = sessions.start(user)
    claims = tokens.decode_access_token(access["token"])
    users.administer(user["username"], "disable")
    users.administer(user["username"], "enable")
    with pytest.raises(jwt.InvalidTokenError):
        sessions.validate(claims, users)
    fresh, _, _ = sessions.start(users.get(user["username"]))
    sessions.validate(tokens.decode_access_token(fresh["token"]), users)


def test_real_cleanup_removes_only_expired_sessions(live):
    users, sessions, user, client, _ = live
    access, _, _ = sessions.start(user)
    claims = tokens.decode_access_token(access["token"])
    active = sessions.get_record(claims["sid"])["_source"]
    client.index(index=sessions.index, id="expired-test-session", body={**active,
        "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}, refresh=True)
    sessions.cleanup()
    assert sessions.get_record("expired-test-session") is None
    sessions.validate(claims, users)
