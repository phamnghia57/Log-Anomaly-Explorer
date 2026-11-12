"""Loopback browser-test fixture using real, uniquely named OpenSearch indexes."""

import importlib
import secrets
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from opensearchpy import OpenSearch
from starlette.datastructures import State
from ingestion.src.storage import OpenSearchLogStore
from clustering.src.storage import OpenSearchStore


@contextmanager
def live_auth_stack(url, username, password, secret):
    prefix = "issue73-browser-" + secrets.token_hex(8)
    names = {kind: prefix + "-" + kind for kind in (
        "users", "sessions", "limits", "logs", "clusters", "history", "quarantine",
    )}
    client = OpenSearch(url, timeout=10, max_retries=0)
    store = OpenSearchLogStore(client, log_index=names["logs"], quarantine_index=names["quarantine"], shards=1, replicas=0)
    now = datetime.now(timezone.utc).isoformat()
    log = {"timestamp": now, "level": "ERROR", "service": "auth-test", "trace_id": "a" * 32,
           "span_id": "b" * 16, "message": "Integration test fault"}
    cluster = {"cluster_id": "auth-test-cluster", "service": "auth-test", "score": 3.0,
               "status": "alerted", "signature": "Integration test fault", "log_ids": ["auth-test-log"],
               "trace_ids": [log["trace_id"]], "first_seen": now, "last_seen": now}
    try:
        with ExitStack() as patches:
            config = importlib.import_module("query-api.src.config")
            patches.enter_context(patch.multiple(config, JWT_SECRET=secret,
                USERS_INDEX=names["users"], AUTH_SESSIONS_INDEX=names["sessions"],
                AUTH_LOGIN_LIMIT_INDEX=names["limits"],
                ADMIN_SEED_USERNAME=username, ADMIN_SEED_PASSWORD=password,
                AUTH_COOKIE_SECURE=False, AUTH_ALLOWED_ORIGINS=("http://127.0.0.1:5174",)))
            main = importlib.import_module("query-api.src.main")
            users = importlib.import_module("query-api.src.users").UserRepository(store)
            sessions = importlib.import_module("query-api.src.sessions").SessionRepository(store)
            users.ensure_ready()
            sessions.ensure_ready()
            limiter = importlib.import_module("query-api.src.login_limits").LoginLimiter(store)
            limiter.ensure_ready()
            users.create_admin(username, password)
            clusters = OpenSearchStore(store)
            clusters.clusters, clusters.history = names["clusters"], names["history"]
            clusters.ensure_ready()
            client.index(index=names["logs"], id="auth-test-log", body=log, refresh=True)
            client.index(index=names["clusters"], id=cluster["cluster_id"], body=cluster, refresh=True)
            client.index(index=names["history"], id="point-1", body={"cluster_id": cluster["cluster_id"],
                         "score": 3.0, "status": "alerted", "recorded_at": now}, refresh=True)
            patches.enter_context(patch.multiple(main, store=store, cluster_store=clusters))
            patches.enter_context(patch.object(main.app, "state", State({
                "store": store, "cluster_store": clusters, "user_repository": users,
                "session_repository": sessions, "login_limiter": limiter, "assistant_conversations": None,
            })))
            yield SimpleNamespace(app=main.app)
    finally:
        for name in names.values():
            client.indices.delete(index=name, ignore=[404])
        client.close()
