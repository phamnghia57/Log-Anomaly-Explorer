"""Additional backend verification for the approved contracts, without mutations."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest

from test_assistant_undo_contract import (
    CLUSTER, CONVERSATION, SEND, TIMESTAMP, UNDO, harness, logs,
    seed_history, turn,
)


def send(harness, message="Next question."):
    response = harness.client.post(SEND, json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def undo(harness, revision):
    return harness.client.post(UNDO, json={"expected_revision": revision})


def test_t02_undo_restores_exact_tool_history_and_creation_time(harness):
    history = turn("Câu hỏi trước") + [
        {"role": "assistant", "content": None, "created_at": TIMESTAMP,
         "tool_calls": [{"id": "call-1", "name": "get_cluster_history", "arguments": "{}"}]},
        {"role": "tool", "content": "{}", "created_at": TIMESTAMP,
         "tool_call_id": "call-1", "name": "get_cluster_history"},
        {"role": "assistant", "content": "Đã kiểm tra.", "created_at": TIMESTAMP},
    ]
    harness.driver.create(index=harness.repository.index, id=CLUSTER, body={
        "cluster_id": CLUSTER, "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP, "messages": history,
    })
    sent = send(harness)
    generated = harness.generation.call_count
    restored = undo(harness, sent["revision"])
    assert restored.status_code == 200
    assert restored.json()["messages"] == history
    state = harness.repository.get(CLUSTER)
    assert state.document["created_at"] == TIMESTAMP
    assert state.document["undo"] is None
    assert "undo" not in restored.json()
    assert harness.generation.call_count == generated


def test_t04_t05_one_level_undo_is_consumed_and_old_revision_conflicts(harness):
    first = send(harness, "A")
    second = send(harness, "B")
    restored = undo(harness, second["revision"])
    assert restored.status_code == 200
    assert restored.json()["messages"] == first["messages"]
    before = harness.driver.snapshot(index=harness.repository.index, id=CLUSTER)
    harness.driver.clear_activity()
    assert undo(harness, second["revision"]).json() == {"detail": "revision_conflict"}
    response = undo(harness, restored.json()["revision"])
    assert response.status_code == 409
    assert response.json() == {"detail": "nothing_to_undo"}
    assert harness.driver.write_attempts == []
    assert harness.driver.snapshot(index=harness.repository.index, id=CLUSTER) == before


@pytest.mark.parametrize("payload", [
    {}, {"message": None}, {"message": 1}, {"message": True},
    {"message": []}, {"message": {}}, {"message": ""},
    {"message": "x" * 4001}, {"message": "hi", "extra": True},
])
def test_t06_invalid_send_inputs_have_no_side_effects(harness, payload):
    response = harness.client.post(SEND, json=payload)
    assert response.status_code == 422
    assert harness.generation.call_count == 0
    assert harness.driver.write_attempts == []


@pytest.mark.parametrize("message", ["x", "x" * 3999, "x" * 4000, "😀" * 4000, " hi "])
def test_t07_valid_boundary_messages_preserve_accepted_text(harness, message):
    assert send(harness, message)["messages"][0]["content"] == message


@pytest.mark.parametrize("revision", [
    None, 1, True, "", " ", "1", "0:0", "01:0", "1:00", "1:-1",
    "+1:0", "1:+0", " 1:0", "1:0\n", "１:０", "1:0:0",
    "9223372036854775808:0", "1:9223372036854775808", "1" * 100 + ":0",
])
def test_t08_invalid_revisions_are_422_without_reads_or_writes(harness, revision):
    # Any attempt to read storage would become 503 rather than the required 422.
    harness.driver.read_error = ConnectionError("read must not occur")
    response = undo(harness, revision)
    assert response.status_code == 422
    assert harness.driver.write_attempts == []
    assert harness.generation.call_count == 0


@pytest.mark.parametrize("payload", [{}, {"expected_revision": "1:0", "extra": True}])
def test_t08_undo_request_requires_only_the_revision_field(harness, payload):
    assert harness.client.post(UNDO, json=payload).status_code == 422
    assert harness.driver.write_attempts == []


@pytest.mark.parametrize("revision", ["1:0", "9223372036854775807:9223372036854775807"])
def test_t09_valid_version_boundaries_are_accepted_but_missing_state_conflicts(harness, revision):
    response = undo(harness, revision)
    assert response.status_code == 409
    assert response.json() == {"detail": "revision_conflict"}


def test_t10_stale_revision_does_not_touch_newer_history(harness):
    first = send(harness, "A")
    send(harness, "B")
    before = harness.driver.snapshot(index=harness.repository.index, id=CLUSTER)
    harness.driver.clear_activity()
    response = undo(harness, first["revision"])
    assert response.status_code == 409
    assert response.json() == {"detail": "revision_conflict"}
    assert harness.driver.write_attempts == []
    assert harness.driver.snapshot(index=harness.repository.index, id=CLUSTER) == before


def test_t13_rejected_undo_write_is_503_and_preserves_snapshot(harness, monkeypatch):
    sent = send(harness)
    before = harness.driver.snapshot(index=harness.repository.index, id=CLUSTER)

    def unavailable(**kwargs):
        raise ConnectionError("sensitive transport detail must not be exposed")

    monkeypatch.setattr(harness.driver, "index", unavailable)
    response = undo(harness, sent["revision"])
    assert response.status_code == 503
    assert response.json()["error"] == "storage_unavailable"
    assert "sensitive transport detail" not in response.text
    assert harness.driver.snapshot(index=harness.repository.index, id=CLUSTER) == before


@pytest.mark.parametrize("operation", ["undo", "send"])
def test_t15_t16_competing_undo_mutations_use_the_same_version(harness, monkeypatch, operation):
    seed_history(harness)
    sent = send(harness)
    before_history = turn("Previously committed question.")
    barrier = Barrier(2, timeout=10)
    original_get = harness.driver.get

    def synchronized_get(**kwargs):
        response = original_get(**kwargs)
        barrier.wait()
        return response

    with monkeypatch.context() as patch:
        patch.setattr(harness.driver, "get", synchronized_get)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(undo, harness, sent["revision"])
            second = (pool.submit(undo, harness, sent["revision"]) if operation == "undo"
                      else pool.submit(harness.client.post, SEND, json={"message": "Racing send"}))
            responses = [first.result(timeout=15), second.result(timeout=15)]
    assert not barrier.broken
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert harness.repository.get(CLUSTER).document["messages"] == winner["messages"]
    if operation == "undo":
        assert winner["messages"] == before_history


def test_t18_mapping_update_preserves_legacy_data_and_is_idempotent(harness):
    seed_history(harness)
    harness.driver.mappings[harness.repository.index]["mappings"]["properties"].pop("undo")
    before = harness.driver.snapshot(index=harness.repository.index, id=CLUSTER)
    harness.repository.ensure_ready()
    harness.repository.ensure_ready()
    assert harness.driver.snapshot(index=harness.repository.index, id=CLUSTER) == before
    properties = harness.driver.mappings[harness.repository.index]["mappings"]["properties"]
    assert properties["messages"] == {"type": "object", "dynamic": False}
    assert properties["undo"] == {"type": "object", "enabled": False}
    response = harness.client.get(CONVERSATION)
    assert response.status_code == 200
    assert response.json()["messages"] == before["_source"]["messages"]
    assert response.json()["undo_available"] is False
    assert undo(harness, response.json()["revision"]).json() == {"detail": "nothing_to_undo"}


@pytest.mark.parametrize("failure", ["exception", "unacknowledged"])
def test_t18_mapping_failures_are_storage_errors(harness, monkeypatch, failure):
    def update(**kwargs):
        if failure == "exception":
            raise ConnectionError("mapping failed")
        return {"acknowledged": False}

    monkeypatch.setattr(harness.driver.indices, "put_mapping", update)
    with pytest.raises(logs.StorageError):
        harness.repository.ensure_ready()


@pytest.mark.parametrize("authorization", [None, "Bearer invalid"])
def test_t19_undo_keeps_admin_authentication(harness, authorization):
    harness.client.headers.pop("Authorization", None)
    if authorization:
        harness.client.headers["Authorization"] = authorization
    harness.driver.read_error = ConnectionError("must not read")
    response = undo(harness, "1:0")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert harness.driver.write_attempts == []


def test_t22_corrupt_snapshot_is_not_an_empty_success(harness):
    harness.driver.create(index=harness.repository.index, id=CLUSTER, body={
        "cluster_id": CLUSTER, "created_at": TIMESTAMP, "updated_at": TIMESTAMP,
        "messages": turn("A"), "undo": {"messages": "not an array"},
    })
    harness.driver.clear_activity()
    response = undo(harness, "1:0")
    assert response.status_code == 503
    assert response.json()["error"] == "storage_unavailable"
    assert harness.driver.write_attempts == []


def test_snapshot_and_saved_data_do_not_alias_caller_objects(harness):
    seed_history(harness)
    previous = harness.repository.get(CLUSTER)
    history = deepcopy(previous.document["messages"])
    messages = deepcopy(history) + turn("B")
    saved = harness.repository.save(CLUSTER, messages, previous=previous)
    attempt = harness.driver.write_attempts[-1]
    assert (attempt["if_seq_no"], attempt["if_primary_term"]) == (previous.seq_no, previous.primary_term)
    messages[0]["content"] = "caller mutation"
    previous.document["messages"].clear()
    assert saved.document["undo"]["messages"] == history
    assert saved.document["messages"][0]["content"] == history[0]["content"]
    assert harness.repository.get(CLUSTER).document == saved.document


@pytest.mark.parametrize("metadata", [{}, {"_seq_no": True, "_primary_term": 1}])
def test_invalid_version_metadata_is_not_defaulted(harness, monkeypatch, metadata):
    seed_history(harness)
    document = harness.driver.snapshot(index=harness.repository.index, id=CLUSTER)["_source"]
    monkeypatch.setattr(harness.driver, "get", lambda **kwargs: {"found": True, "_source": document} | metadata)
    response = harness.client.post(SEND, json={"message": "B"})
    assert response.status_code == 503
    assert harness.driver.write_attempts == []
    assert harness.generation.call_count == 0
