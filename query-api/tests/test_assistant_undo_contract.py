"""VT-013 RED contracts: real routes/repository, fake storage transport and AI.

No xfail, fallback response fields, dependency overrides, or production changes.
The fake models OpenSearch, not Undo; HTTP outcomes and durable state are the
oracles. See docs/assignments/VT-013/plan.md for the approved public contract.
"""

from concurrent.futures import ThreadPoolExecutor
import importlib
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from opensearchpy.exceptions import ConflictError, NotFoundError

from vt013_opensearch_fake import RevisionedOpenSearch

main = importlib.import_module("query-api.src.main")
router = importlib.import_module("query-api.src.assistant.router")
storage = importlib.import_module("query-api.src.assistant.storage")
logs = importlib.import_module("ingestion.src.storage")

CLUSTER = "vt013-contract-cluster"
CONVERSATION = f"/assistant/clusters/{CLUSTER}/conversation"
SEND = f"{CONVERSATION}/messages"
UNDO = f"{CONVERSATION}/undo"
TIMESTAMP = "2026-11-08T00:00:00+00:00"


def turn(message):
    return [
        {"role": "user", "content": message, "created_at": TIMESTAMP},
        {"role": "assistant", "content": "Deterministic test answer.",
         "created_at": TIMESTAMP},
    ]


@pytest.fixture
def harness(monkeypatch, admin_auth):
    driver = RevisionedOpenSearch()
    repository = storage.ConversationRepository(logs.OpenSearchLogStore(driver))
    repository.ensure_ready()
    generation = Mock(side_effect=lambda **kwargs: turn(kwargs["user_message"]))
    monkeypatch.setattr(router, "run_chat_turn", generation)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "vt013-test-key-not-real")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://vt013.invalid/")

    # Restore State explicitly, following existing Assistant fixtures: using
    # monkeypatch.setattr(State, ...) can delete rather than restore attributes.
    original = {key: getattr(main.app.state, key) for key in (
        "store", "cluster_store", "assistant_conversations",
    )}
    main.app.state.store = logs.InMemoryLogStore()
    main.app.state.cluster_store = SimpleNamespace(
        get_cluster=lambda cluster_id: {
            "cluster_id": CLUSTER, "log_ids": [],
        } if cluster_id == CLUSTER else None,
    )
    main.app.state.assistant_conversations = repository
    try:
        with TestClient(main.app, headers=admin_auth) as client:
            yield SimpleNamespace(client=client, driver=driver,
                                  repository=repository, generation=generation)
    finally:
        for key, value in original.items():
            setattr(main.app.state, key, value)


def seed_history(harness):
    history = turn("Previously committed question.")
    harness.driver.index(index=harness.repository.index, id=CLUSTER, body={
        "cluster_id": CLUSTER, "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP, "messages": history,
    })
    harness.driver.clear_activity()
    return history


def test_t03_send_response_exposes_revision_contract(harness):
    """AC-01: Send must expose the revision that clients use for Undo."""
    response = harness.client.post(SEND, json={"message": "First question."})
    assert response.status_code == 200
    assert response.json() == {
        "cluster_id": CLUSTER, "messages": turn("First question."),
        "revision": "1:0", "undo_available": True,
    }


def test_t03_undo_first_send_persists_empty_history(harness):
    """AC-01: exercise Undo even while Send's public revision is still missing."""
    assert harness.driver.snapshot(index=harness.repository.index, id=CLUSTER) is None
    sent = harness.client.post(SEND, json={"message": "First question."})
    assert sent.status_code == 200
    # This is the storage provider's current version, not a response-field
    # fallback. The companion test independently requires Send to expose it.
    before = harness.driver.get(index=harness.repository.index, id=CLUSTER)
    current_revision = f"{before['_primary_term']}:{before['_seq_no']}"
    response = harness.client.post(UNDO, json={"expected_revision": current_revision})
    assert response.status_code == 200
    body = response.json()
    assert body["cluster_id"] == CLUSTER
    assert body["messages"] == []
    assert body["undo_available"] is False
    assert isinstance(body["revision"], str)
    assert body["revision"] != current_revision
    assert sent.json()["revision"] == current_revision
    persisted = harness.driver.get(index=harness.repository.index, id=CLUSTER)
    assert persisted["_source"]["messages"] == []
    assert body["revision"] == f"{persisted['_primary_term']}:{persisted['_seq_no']}"
    assert harness.client.get(CONVERSATION).json() == body
    assert harness.generation.call_count == 1  # Undo must not generate a turn.


@pytest.mark.parametrize("message", [" ", "\t\r\n", " \u00a0 "],
                         ids=["space", "tabs-newlines", "nonbreaking-space"])
def test_t06_whitespace_message_is_rejected_without_side_effects(harness, message):
    """AC-02: direct HTTP calls must receive the same blank-input protection."""
    response = harness.client.post(SEND, json={"message": message})
    observed = {
        "status": response.status_code,
        "generation_calls": harness.generation.call_count,
        "write_attempts": len(harness.driver.write_attempts),
        "stored_document": harness.driver.snapshot(index=harness.repository.index, id=CLUSTER),
    }
    assert observed == {"status": 422, "generation_calls": 0,
                        "write_attempts": 0, "stored_document": None}


def test_t11_read_failure_returns_503_and_preserves_history(harness):
    """AC-04: real repository wraps a transport failure; no default history."""
    seed_history(harness)
    before = harness.driver.snapshot(index=harness.repository.index, id=CLUSTER)
    harness.driver.read_error = ConnectionError("VT-013 injected read failure")
    response = harness.client.post(SEND, json={"message": "Next question."})
    assert response.status_code == 503
    assert response.json()["error"] == "storage_unavailable"
    assert harness.generation.call_count == 0
    assert harness.driver.write_attempts == []
    assert harness.driver.snapshot(index=harness.repository.index, id=CLUSTER) == before


def test_t12_missing_index_raises_storage_error_in_actual_repository(harness):
    """AC-04: a missing index is different from a missing document."""
    harness.driver.indices.delete(index=harness.repository.index)
    with pytest.raises(logs.StorageError):
        harness.repository.get(CLUSTER)


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_t12_missing_index_returns_503_not_empty_success(harness, method):
    harness.driver.indices.delete(index=harness.repository.index)
    kwargs = {"json": {"message": "Next question."}} if method == "POST" else {}
    response = harness.client.request(method, SEND if method == "POST" else CONVERSATION,
                                      **kwargs)
    observed = {"status": response.status_code,
                "generation_calls": harness.generation.call_count,
                "write_attempts": len(harness.driver.write_attempts)}
    assert observed == {"status": 503, "generation_calls": 0, "write_attempts": 0}
    assert response.json()["error"] == "storage_unavailable"


@pytest.mark.parametrize("existing", [True, False], ids=["existing-document", "first-creation"])
def test_t14_concurrent_sends_cannot_silently_overwrite(harness, existing):
    """AC-05: both requests finish reading the same version before either writes."""
    history = seed_history(harness) if existing else []
    barrier = Barrier(2, timeout=10)

    def synchronized_generation(**kwargs):
        assert kwargs["history"] == history
        barrier.wait()  # Bounded synchronization, not a timing-dependent sleep.
        return turn(kwargs["user_message"])

    harness.generation.side_effect = synchronized_generation
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(harness.client.post, SEND, json={"message": message})
                   for message in ("Concurrent A", "Concurrent B")]
        responses = [future.result(timeout=15) for future in futures]
    assert not barrier.broken, "Test infrastructure: both requests must reach generation"
    observed = {"statuses": sorted(response.status_code for response in responses),
                "commits": len(harness.driver.commits)}
    assert observed == {"statuses": [200, 409], "commits": 1}
    winner = next(response.json() for response in responses if response.status_code == 200)
    loser = next(response.json() for response in responses if response.status_code == 409)
    assert loser == {"detail": "revision_conflict"}
    persisted = harness.driver.get(index=harness.repository.index, id=CLUSTER)
    assert persisted["_source"]["messages"] == winner["messages"]
    assert winner["messages"][:len(history)] == history
    assert len(winner["messages"]) == len(history) + 2


def test_fake_copies_documents_and_does_not_protect_unconditional_writes():
    """Infrastructure control: the double must not implement lost-update prevention."""
    driver = RevisionedOpenSearch()
    original = {"messages": turn("Original")}
    first = driver.index(index="test", id="c1", body=original)
    original["messages"].clear()
    fetched = driver.get(index="test", id="c1")
    assert fetched["_source"]["messages"] == turn("Original")
    fetched["_source"]["messages"].clear()
    assert driver.get(index="test", id="c1")["_source"]["messages"] == turn("Original")
    second = driver.index(index="test", id="c1", body={"messages": []})
    assert (first["_seq_no"], second["_seq_no"]) == (0, 1)
    assert len(driver.commits) == 2


def test_fake_enforces_explicit_conditional_and_create_only_writes():
    driver = RevisionedOpenSearch()
    first = driver.create(index="test", id="c1", body={"messages": []})
    driver.index(index="test", id="c1", body={"messages": turn("Winner")},
                 if_seq_no=first["_seq_no"], if_primary_term=first["_primary_term"])
    before = driver.snapshot(index="test", id="c1")
    with pytest.raises(ConflictError):
        driver.index(index="test", id="c1", body={"messages": []},
                     if_seq_no=first["_seq_no"], if_primary_term=first["_primary_term"])
    with pytest.raises(ConflictError):
        driver.create(index="test", id="c1", body={"messages": []})
    assert driver.snapshot(index="test", id="c1") == before
    assert len(driver.commits) == 2


def test_fake_preserves_missing_index_exception_and_ignore_semantics():
    driver = RevisionedOpenSearch()
    with pytest.raises(NotFoundError) as error:
        driver.get(index="missing", id="c1")
    assert error.value.error == "index_not_found_exception"
    ignored = driver.get(index="missing", id="c1", ignore=[404])
    assert ignored == {"error": {"type": "index_not_found_exception"}, "status": 404}
