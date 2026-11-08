"""Opt-in HTTP contracts against an owned disposable OpenSearch 2.17.1.

Use evidence/integration/run_integration.py: an explicit context is required.
The context pins both the loopback endpoint and a unique cluster identity.
No existing indexes are deleted/reset, and the persistence layer is never faked.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib import import_module
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError, RequestError
import pytest

from vt013_integration_server import CLUSTER, TIMESTAMP, turn

ROOT = Path(__file__).resolve().parents[2]
CONVERSATION = f"/assistant/clusters/{CLUSTER}/conversation"
storage = import_module("query-api.src.assistant.storage")
log_storage = import_module("ingestion.src.storage")


def history():
    return [
        {"role": "user", "content": "Điều tra 🔎\n", "created_at": TIMESTAMP},
        {"role": "assistant", "content": None, "created_at": TIMESTAMP,
         "tool_calls": [{"id": "call-1", "name": "get_cluster_history", "arguments": "{}"}]},
        {"role": "tool", "content": "[]", "created_at": TIMESTAMP,
         "tool_call_id": "call-1", "name": "get_cluster_history"},
        {"role": "assistant", "content": "", "created_at": TIMESTAMP},
    ]


@pytest.fixture(scope="session")
def instance():
    context_path = os.environ.get("VT013_INTEGRATION_CONTEXT")
    if not context_path:
        pytest.skip("Opt-in: run evidence/integration/run_integration.py")
    context = json.loads(Path(context_path).read_text(encoding="utf-8"))
    endpoint = urlparse(context["url"])
    assert endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1"
    assert context["cluster_name"] == f"vt013-integration-{context['run_id']}"
    assert len(context["run_id"]) == 16 and all(c in "0123456789abcdef" for c in context["run_id"])
    client = OpenSearch(hosts=[context["url"]], timeout=10, max_retries=0)
    info = client.info()
    assert info["version"]["number"] == "2.17.1"
    assert info["cluster_name"] == context["cluster_name"], "Refuse an unowned/shared instance"
    artifacts = Path(os.environ["VT013_INTEGRATION_ARTIFACTS"])
    artifacts.mkdir(parents=True, exist_ok=True)
    yield SimpleNamespace(client=client, context=context, artifacts=artifacts)
    client.close()


class APIProcess:
    def __init__(self, namespace, mode="normal", unreachable_url=""):
        self.namespace = namespace
        self.mode = mode
        self.unreachable_url = unreachable_url
        self.process = None

    def __enter__(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        ns = self.namespace
        prefix = ns.prefix
        self.events = ns.instance.artifacts / f"{prefix}-{self.mode}.events.jsonl"
        self.log_path = ns.instance.artifacts / f"{prefix}-{self.mode}.api.log"
        self.log = self.log_path.open("ab")
        env = os.environ.copy()
        env.update(
            STORAGE_BACKEND="opensearch", OPENSEARCH_URL=ns.instance.context["url"],
            OPENSEARCH_USER="", OPENSEARCH_PASSWORD="", OPENSEARCH_TIMEOUT="3",
            OPENSEARCH_SHARDS="1", OPENSEARCH_REPLICAS="0",
            LOG_INDEX=prefix + "-logs", QUARANTINE_INDEX=prefix + "-quarantine",
            CLUSTER_INDEX=prefix + "-clusters", HISTORY_INDEX=prefix + "-history",
            USERS_INDEX=prefix + "-users", ASSISTANT_CONVERSATIONS_INDEX=ns.index,
            JWT_SECRET=ns.secret, JWT_EXPIRY_SECONDS="3600",
            ADMIN_SEED_USERNAME="vt013-admin", ADMIN_SEED_PASSWORD=ns.password,
            AZURE_OPENAI_API_KEY="test-only-unused", AZURE_OPENAI_ENDPOINT="https://vt013.invalid/",
            OTEL_EXPORTER_OTLP_ENDPOINT="", LANGFUSE_TRACING_ENABLED="false",
            PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
            VT013_SERVER_MODE=self.mode, VT013_API_PORT=str(port),
            VT013_SERVER_EVENTS=str(self.events), VT013_MISSING_INDEX=prefix + "-missing",
            VT013_UNREACHABLE_URL=self.unreachable_url,
        )
        for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            env.pop(key, None)
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-B", str(Path(__file__).with_name("vt013_integration_server.py"))],
            cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=40, trust_env=False)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise AssertionError(f"API exited: {self.log_path.read_text(encoding='utf-8')}")
                try:
                    if self.client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                # Startup polling only. Concurrency tests use barriers, never sleeps.
                time.sleep(0.1)
            else:
                raise AssertionError(f"API readiness timeout: {self.log_path}")
            login = self.client.post("/auth/login", json={
                "username": "vt013-admin", "password": ns.password,
            })
            assert login.status_code == 200, login.text
            self.client.headers["Authorization"] = f"Bearer {login.json()['token']}"
            with (ns.instance.artifacts / "processes.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"prefix": prefix, "mode": self.mode,
                                         "pid": self.process.pid}) + "\n")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        self.client.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.log.close()

    def send(self, message="New question"):
        return self.client.post(CONVERSATION + "/messages", json={"message": message})

    def undo(self, revision):
        return self.client.post(CONVERSATION + "/undo", json={"expected_revision": revision})


@pytest.fixture
def namespace(instance, request):
    prefix = f"vt013-{instance.context['run_id']}-{uuid4().hex[:10]}"
    ns = SimpleNamespace(instance=instance, prefix=prefix, index=prefix + "-conversations",
                         secret=secrets.token_urlsafe(48), password=secrets.token_urlsafe(24))
    # These are fresh, test-specific indexes; no delete/reset is ever issued.
    assert not instance.client.indices.exists(index=prefix + "-clusters")
    instance.client.indices.create(index=prefix + "-clusters", body={
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    })
    instance.client.create(index=prefix + "-clusters", id=CLUSTER, body={
        "cluster_id": CLUSTER, "log_ids": [], "trace_ids": [], "signature": "vt013",
        "score": 3.0, "status": "anomalous", "first_seen": TIMESTAMP, "last_seen": TIMESTAMP,
    }, refresh="wait_for")
    yield ns
    docs = instance.client.get(index=ns.index, id=CLUSTER, ignore=[404])
    # Record the final real document and version even when an assertion failed.
    (instance.artifacts / f"{request.node.name}.persisted.json").write_text(
        json.dumps({"index": ns.index, "document": docs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")


def seed(ns, messages, *, snapshot=None, legacy_mapping=False):
    mapping = deepcopy(storage.CONVERSATION_MAPPING)
    if legacy_mapping:
        del mapping["properties"]["undo"]
    ns.instance.client.indices.create(index=ns.index, body={
        "settings": {"number_of_shards": 1, "number_of_replicas": 0}, "mappings": mapping,
    })
    document = {"cluster_id": CLUSTER, "created_at": TIMESTAMP,
                "updated_at": TIMESTAMP, "messages": deepcopy(messages)}
    if snapshot is not None:
        document["undo"] = {"messages": deepcopy(snapshot)}
    return ns.instance.client.create(index=ns.index, id=CLUSTER, body=document, refresh="wait_for")


def persisted(ns):
    return ns.instance.client.get(index=ns.index, id=CLUSTER)


def revision(raw):
    return f"{raw['_primary_term']}:{raw['_seq_no']}"


def assert_public(response, messages, *, undo_available):
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {"cluster_id", "messages", "revision", "undo_available"}
    assert result["cluster_id"] == CLUSTER
    assert result["messages"] == messages
    assert result["undo_available"] is undo_available
    storage.parse_revision(result["revision"])
    return result


def test_i01_create_send_undo_get(namespace):
    """AC-01: second completed Send restores exactly the first completed turn."""
    with APIProcess(namespace) as api:
        first = assert_public(api.send("First"), turn("First"), undo_available=True)
        second = assert_public(api.send("Second"), turn("First") + turn("Second"), undo_available=True)
        assert second["revision"] != first["revision"]
        restored = assert_public(api.undo(second["revision"]), turn("First"), undo_available=False)
        assert restored["revision"] != second["revision"]
        assert api.client.get(CONVERSATION).json() == restored
        raw = persisted(namespace)
        assert raw["_source"]["messages"] == turn("First")
        assert raw["_source"]["undo"] is None
        assert revision(raw) == restored["revision"]


def test_i02_restore_exact_tool_history(namespace):
    """AC-01: real _source retains order, Unicode, null, tool fields and timestamps."""
    original = history()
    seed(namespace, original)
    with APIProcess(namespace) as api:
        sent = assert_public(api.send(), original + turn("New question"), undo_available=True)
        assert persisted(namespace)["_source"]["undo"] == {"messages": original}
        restored = assert_public(api.undo(sent["revision"]), original, undo_available=False)
        raw = persisted(namespace)
        assert raw["_source"]["messages"] == original
        assert raw["_source"]["created_at"] == TIMESTAMP
        assert raw["_source"]["updated_at"] != TIMESTAMP
        assert revision(raw) == restored["revision"]


def test_i03_first_send_restores_persisted_empty(namespace):
    """T-03 / AC-01: persisted empty differs from an absent conversation."""
    with APIProcess(namespace) as api:
        assert api.client.get(CONVERSATION).json() == {
            "cluster_id": CLUSTER, "messages": [], "revision": None, "undo_available": False,
        }
        sent = assert_public(api.send(), turn("New question"), undo_available=True)
        restored = assert_public(api.undo(sent["revision"]), [], undo_available=False)
        assert restored["revision"] != sent["revision"]
        raw = persisted(namespace)
        assert raw["found"] is True and raw["_source"]["messages"] == []
        assert raw["_source"]["undo"] is None
        assert revision(raw) == restored["revision"]
        assert api.client.get(CONVERSATION).json() == restored
        assert api.undo(sent["revision"]).status_code == 409
        repeat = api.undo(restored["revision"])
        assert repeat.status_code == 409 and repeat.json() == {"detail": "nothing_to_undo"}
        assert persisted(namespace) == raw


def test_i04_restart_api_process_recovers_restored_history(namespace):
    """AC-01: two independent OS processes read the same durable restored state."""
    seed(namespace, history())
    with APIProcess(namespace) as api:
        sent = api.send().json()
        restored = assert_public(api.undo(sent["revision"]), history(), undo_available=False)
        old_pid = api.process.pid
    raw = persisted(namespace)
    with APIProcess(namespace) as restarted:
        assert restarted.process.pid != old_pid
        assert restarted.client.get(CONVERSATION).json() == restored
        assert persisted(namespace) == raw


@pytest.mark.parametrize("existing", [False, True], ids=["create-only", "conditional-update"])
def test_i05_concurrent_sends_have_one_commit(namespace, existing):
    """T-14 / AC-05: barriers synchronize real reads; SDK/server arbitrate writes."""
    original = history() if existing else []
    if existing:
        seed(namespace, original)
    with APIProcess(namespace, "concurrent-send") as api:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(api.send, ["Request A", "Request B"]))
        assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
        winner = next(r.json() for r in results if r.status_code == 200)
        loser = next(r for r in results if r.status_code == 409)
        assert loser.json() == {"detail": "revision_conflict"}
        raw = persisted(namespace)
        assert raw["_source"]["messages"] == winner["messages"]
        assert winner["messages"] in [original + turn("Request A"), original + turn("Request B")]
        assert raw["_source"]["undo"] == {"messages": original}
        assert revision(raw) == winner["revision"]
        # One write only: sequence numbers are compared only within this fresh single-document shard.
        assert raw["_seq_no"] == (1 if existing else 0)
        assert api.client.get(CONVERSATION).json() == winner


def test_i06_concurrent_undos_have_one_commit(namespace):
    """T-15 / AC-05: two actual reads precede conditional Undo writes."""
    raw = seed(namespace, history() + turn("Completed"), snapshot=history())
    with APIProcess(namespace, "concurrent-undo") as api:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(api.undo, [revision(raw)] * 2))
        assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
        winner = next(r for r in results if r.status_code == 200)
        restored = assert_public(winner, history(), undo_available=False)
        assert next(r.json() for r in results if r.status_code == 409) == {"detail": "revision_conflict"}
        final = persisted(namespace)
        assert final["_source"]["messages"] == history() and final["_source"]["undo"] is None
        assert final["_seq_no"] == raw["_seq_no"] + 1
        assert revision(final) == restored["revision"]
        assert api.client.get(CONVERSATION).json() == restored


def test_i07_missing_document_versus_missing_index(namespace):
    """T-12 / AC-04: actual SDK NotFoundError shapes, repository and HTTP contracts."""
    with APIProcess(namespace) as api:
        assert api.client.get(CONVERSATION).json() == {
            "cluster_id": CLUSTER, "messages": [], "revision": None, "undo_available": False,
        }
    missing = namespace.prefix + "-missing"
    observed = {}
    for key, index in [("document", namespace.index), ("index", missing)]:
        with pytest.raises(NotFoundError) as error:
            namespace.instance.client.get(index=index, id=CLUSTER)
        observed[key] = {"status": error.value.status_code, "error": error.value.error,
                         "info": error.value.info}
    assert observed["document"]["info"]["found"] is False
    assert observed["index"]["error"] == "index_not_found_exception"
    repository = storage.ConversationRepository(log_storage.OpenSearchLogStore(namespace.instance.client))
    repository.index = namespace.index
    assert repository.get(CLUSTER) is None
    repository.index = missing
    with pytest.raises(log_storage.StorageError):
        repository.get(CLUSTER)
    with APIProcess(namespace, "missing-index") as api:
        for response in (api.client.get(CONVERSATION), api.send()):
            assert response.status_code == 503
            assert response.json()["error"] == "storage_unavailable"
        assert not api.events.exists(), "Storage failure must precede generation"
    assert not namespace.instance.client.indices.exists(index=missing)
    assert not namespace.instance.client.exists(index=namespace.index, id=CLUSTER)
    (namespace.instance.artifacts / "not-found-shapes.json").write_text(
        json.dumps(observed, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_i08_existing_strict_mapping_is_upgraded_additively(namespace):
    """T-18 / AC-01,04: startup adds undo to a real legacy strict index."""
    seed(namespace, history(), legacy_mapping=True)
    client = namespace.instance.client
    before = client.indices.get_mapping(index=namespace.index)[namespace.index]["mappings"]
    old_document = persisted(namespace)
    assert before["dynamic"] == "strict" and "undo" not in before["properties"]
    with APIProcess(namespace) as api:
        after = client.indices.get_mapping(index=namespace.index)[namespace.index]["mappings"]
        assert after["dynamic"] == "strict"
        assert after["properties"]["undo"] == {"type": "object", "enabled": False}
        assert {k: v for k, v in after["properties"].items() if k != "undo"} == before["properties"]
        assert persisted(namespace) == old_document
        assert_public(api.client.get(CONVERSATION), history(), undo_available=False)
        sent = api.send().json()
        assert_public(api.undo(sent["revision"]), history(), undo_available=False)
        assert persisted(namespace)["_source"]["messages"] == history()
        with pytest.raises(RequestError) as error:
            client.index(index=namespace.index, id="invalid-extra-field", body={"unexpected": 1})
        assert error.value.status_code == 400
    (namespace.instance.artifacts / "mapping-upgrade.json").write_text(
        json.dumps({"before": before, "after": after}, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_i09_legacy_document_remains_readable(namespace):
    """AC-01,03: no synthesized snapshot for a legacy document."""
    seed(namespace, history())
    before = persisted(namespace)
    with APIProcess(namespace) as api:
        result = assert_public(api.client.get(CONVERSATION), history(), undo_available=False)
        assert result["revision"] == revision(before)
        denied = api.undo(result["revision"])
        assert denied.status_code == 409 and denied.json() == {"detail": "nothing_to_undo"}
        assert persisted(namespace) == before


def test_i10_real_connection_failure_propagates_without_data_loss(namespace):
    """T-11 / AC-04: SDK connection refusal becomes 503, never default history."""
    seed(namespace, history())
    before = persisted(namespace)
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))  # Reserved but not listening; no service can take this port.
        url = f"http://127.0.0.1:{unavailable.getsockname()[1]}"
        with APIProcess(namespace, "read-failure", url) as api:
            response = api.send()
            assert response.status_code == 503, response.text
            assert response.json()["error"] == "storage_unavailable"
            assert not api.events.exists()
            assert persisted(namespace) == before


def test_i11_real_write_rejection_preserves_snapshot(namespace):
    """T-13 / AC-04: an actual OpenSearch write block is propagated."""
    seed(namespace, history() + turn("Completed"), snapshot=history())
    before = persisted(namespace)
    namespace.instance.client.indices.put_settings(index=namespace.index, body={"index.blocks.write": True})
    with APIProcess(namespace) as api:
        response = api.undo(revision(before))
        assert response.status_code == 503, response.text
        assert response.json()["error"] == "storage_unavailable"
        assert persisted(namespace) == before
        assert not api.events.exists()


def test_i12_validation_and_admin_auth_remain_enforced(namespace):
    """AC-02,03: boundary inputs use HTTP validators; missing JWT never reaches mutation."""
    with APIProcess(namespace) as api:
        with httpx.Client(base_url=api.client.base_url, trust_env=False) as unauthenticated:
            responses = [unauthenticated.get(CONVERSATION),
                         unauthenticated.post(CONVERSATION + "/messages", json={"message": "x"}),
                         unauthenticated.post(CONVERSATION + "/undo", json={"expected_revision": "1:0"})]
        for response in responses:
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
        for message in ("", " \t\n", "x" * 4001, 7, None):
            assert api.send(message).status_code == 422
        for token in ("", "01:0", "1:-1", "1:9223372036854775808", 1):
            assert api.undo(token).status_code == 422
        assert not api.events.exists()
        assert not namespace.instance.client.exists(index=namespace.index, id=CLUSTER)
        for message in ("x", "🔎" * 4000):
            sent = api.send(message)
            assert sent.status_code == 200, sent.text
            assert sent.json()["messages"][-2]["content"] == message
        assert persisted(namespace)["_source"]["messages"] == turn("x") + turn("🔎" * 4000)
