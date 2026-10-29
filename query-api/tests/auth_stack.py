"""Test-only auth stack: real routes/storage abstractions, mocked OpenSearch client.

Never imported by the production app. No network or persistent test database.
"""

import importlib
import secrets
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from opensearchpy.exceptions import ConflictError, NotFoundError
from starlette.datastructures import State

from clustering.src.storage import OpenSearchStore
from ingestion.src.storage import OpenSearchLogStore


@contextmanager
def auth_stack(*, username="integration-admin", password=None, secret=None):
    password = password or secrets.token_urlsafe(32)
    secret = secret or secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc).isoformat()
    log = {"timestamp": now, "level": "ERROR", "service": "auth-test",
           "trace_id": "a" * 32, "span_id": "b" * 16, "message": "Integration test fault"}
    cluster = {"cluster_id": "auth-test-cluster", "score": 3.0, "status": "alerted",
               "log_ids": ["auth-test-log"], "trace_ids": [log["trace_id"]],
               "signature": "Integration test fault", "first_seen": now, "last_seen": now}
    point = {"cluster_id": cluster["cluster_id"], "score": 3.0, "status": "alerted", "recorded_at": now}
    documents = {("auth-test-clusters", cluster["cluster_id"]): cluster,
                 ("auth-test-logs", "auth-test-log"): log,
                 ("auth-test-history", "point-1"): point}
    indexes = {index for index, _ in documents}
    client = Mock()
    client.ping.return_value = True
    client.indices.exists.side_effect = lambda *, index: index in indexes

    def create_index(*, index, body):
        indexes.add(index)
        return {"acknowledged": True}

    def get(*, index, id, **kwargs):
        if (index, id) not in documents:
            raise NotFoundError(404, "not_found")
        return {"found": True, "_source": deepcopy(documents[index, id])}

    def create(*, index, id, body, **kwargs):
        if (index, id) in documents:
            raise ConflictError(409, "version_conflict_engine_exception")
        documents[index, id] = deepcopy(body)
        return {"result": "created"}

    def search(*, index, body, **kwargs):
        hits = [{"_id": id, "_source": deepcopy(doc)} for (name, id), doc in documents.items() if name == index]
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}}

    client.indices.create.side_effect = create_index
    client.get.side_effect = get
    client.create.side_effect = create
    client.search.side_effect = search
    client.mget.side_effect = lambda *, index, body: {"docs": [
        {"found": True, "_id": id, "_source": deepcopy(documents[index, id])} for id in body["ids"]
    ]}
    log_store = OpenSearchLogStore(client, log_index="auth-test-logs", quarantine_index="auth-test-quarantine")
    with ExitStack() as stack:
        stack.enter_context(patch("ingestion.src.storage.build_store", return_value=log_store))
        stack.enter_context(patch("clustering.src.storage.build_store", return_value=log_store))
        config = importlib.import_module("query-api.src.config")
        stack.enter_context(patch.multiple(config, JWT_SECRET=secret, JWT_EXPIRY_SECONDS=3600,
                                           ADMIN_SEED_USERNAME=username, ADMIN_SEED_PASSWORD=password,
                                           USERS_INDEX="auth-test-users"))
        main = importlib.import_module("query-api.src.main")
        repository = importlib.import_module("query-api.src.users").UserRepository(log_store)
        clusters = OpenSearchStore(log_store)
        clusters.clusters, clusters.history = "auth-test-clusters", "auth-test-history"
        stack.enter_context(patch.multiple(main, store=log_store, cluster_store=clusters))
        stack.enter_context(patch.object(main.app, "state", State({"user_repository": repository})))
        yield SimpleNamespace(app=main.app, repository=repository, client=client, documents=documents,
                              credentials={"username": username, "password": password}, secret=secret,
                              cluster=cluster, log=log, point=point)
