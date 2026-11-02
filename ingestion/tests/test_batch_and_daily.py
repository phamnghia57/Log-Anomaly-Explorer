"""Regression tests for batch API, limiter, facets and drop-index retention (no live OS)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import sys
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from ingestion.src import main
from ingestion.src.rate_limit import RateLimiter
from ingestion.src.storage import InMemoryLogStore, OpenSearchLogStore, StorageError


def make_log(level="INFO", hours=0):
    return {
        "timestamp": (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(),
        "level": level, "service": "demo-web", "trace_id": "abc", "span_id": "def",
        "message": "log from batch",
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "store", InMemoryLogStore())
    monkeypatch.setattr(main, "ingest_limiter", RateLimiter(0))
    with TestClient(main.app) as test_client:
        yield test_client


def test_batch_accepted_and_search_facets(client):
    response = client.post("/ingest/batch", json=[make_log(), make_log("ERROR")])
    assert response.status_code == 202
    assert response.json()["count"] == 2
    assert len(set(response.json()["log_ids"])) == 2
    result = client.get("/search", params={"level": "ERROR"}).json()
    assert result["total"] == 1
    assert result["results"][0]["level"] == "ERROR"
    assert result["facets"]["levels"] == [{"key": "ERROR", "doc_count": 1}]
    assert sum(b["doc_count"] for b in result["facets"]["timeline"]) == 1


def test_batch_reject_invalid_atomically_and_quarantine(client):
    response = client.post("/ingest/batch", json=[make_log(), {"broken": True}])
    assert response.status_code == 400
    assert response.json()["invalid"][0]["index"] == 1
    assert len(main.store._quarantine) == 1
    assert client.get("/search").json()["total"] == 0
    assert client.post("/ingest/batch", json=[]).status_code == 400


def test_batch_size_and_input_shape(client, monkeypatch):
    monkeypatch.setattr(main.config, "MAX_BATCH_SIZE", 2)
    assert client.post("/ingest/batch", json=[make_log()] * 3).status_code == 413
    assert client.post("/ingest/batch", json=make_log()).status_code == 422


def test_batch_idempotency_key_same_document_ids(client):
    logs = [make_log(), make_log("ERROR")]
    a = client.post("/ingest/batch", json=logs, headers={"Idempotency-Key": "batch-001"})
    b = client.post("/ingest/batch", json=logs, headers={"Idempotency-Key": "batch-001"})
    assert a.status_code == b.status_code == 202
    assert a.json()["log_ids"] == b.json()["log_ids"]
    assert client.get("/search").json()["total"] == 2
    assert client.post("/ingest/batch", json=logs, headers={"Idempotency-Key": " "}).status_code == 400


def test_rate_limiter_returns_429_for_both_routes(client, monkeypatch):
    monkeypatch.setattr(main, "ingest_limiter", RateLimiter(1))
    assert client.post("/ingest", json=make_log()).status_code == 202
    response = client.post("/ingest/batch", json=[make_log()])
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.json()["reason"] == "rate_limit_exceeded"
    assert client.get("/health").status_code == 200


def test_limiter_sliding_window(monkeypatch):
    import ingestion.src.rate_limit as rate_module
    times = iter([10.0, 10.1, 10.2, 11.01])
    monkeypatch.setattr(rate_module, "monotonic", lambda: next(times))
    limiter = RateLimiter(2)
    assert [limiter.allow() for _ in range(4)] == [True, True, False, True]


class FakeIndices:
    def __init__(self):
        self.data = {}
        self.dropped = []

    def exists(self, index):
        return index in self.data

    def create(self, index, body):
        self.data[index] = body

    def get(self, index, **kwargs):
        prefix = index.split("*")[0].split("?")[0]
        return {name: data for name, data in self.data.items() if name.startswith(prefix)}

    def delete(self, index):
        self.dropped.append(index)
        del self.data[index]


class FakeOpenSearch:
    def __init__(self):
        self.indices = FakeIndices()
        self.requests = []

    def index(self, **kwargs):
        self.requests.append(kwargs)

    def search(self, **kwargs):
        self.requests.append(kwargs)
        return {"hits": {"total": {"value": 1}, "hits": [{"_id": "x", "_source": make_log()}]},
                "aggregations": {"timeline": {"buckets": []},
                                 "levels": {"buckets": [{"key": "INFO", "doc_count": 1}]},
                                 "services": {"buckets": []}}}


def test_opensearch_uses_daily_indices_and_drop_only_whole_expired_days():
    fake = FakeOpenSearch()
    store = OpenSearchLogStore(fake)
    store.ensure_ready()
    old = make_log(hours=-24 * 40)
    today = make_log()
    store.write_log("old", old)
    store.write_log("new", today)
    old_index = store._daily_index(old["timestamp"])
    new_index = store._daily_index(today["timestamp"])
    fake.indices.data["logs"] = {"legacy": True}
    assert old_index in fake.indices.data and new_index in fake.indices.data
    removed = store.delete_older_than((datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    assert removed == 1
    assert fake.indices.dropped == [old_index]
    assert "logs" in fake.indices.data and new_index in fake.indices.data
    _, _, facets = store.search_with_facets(level="INFO", service="demo-web")
    req = fake.requests[-1]
    assert req["index"] == store.read_index
    assert {"term": {"level": "INFO"}} in req["body"]["query"]["bool"]["filter"]
    assert "date_histogram" in req["body"]["aggs"]["timeline"]
    assert facets["levels"][0]["doc_count"] == 1


def test_daily_retention_does_not_drop_partially_expired_day():
    fake = FakeOpenSearch()
    store = OpenSearchLogStore(fake)
    fake.indices.data = {"logs-2026.10.01": {}, "logs-2026.10.02": {},
                         "logs-quarantine": {}, "logs": {}}
    removed = store.delete_older_than("2026-10-02T12:00:00+00:00")
    assert removed == 1
    assert fake.indices.dropped == ["logs-2026.10.01"]
    assert "logs-2026.10.02" in fake.indices.data


def test_opensearch_bulk_single_call_and_partial_failure(monkeypatch):
    fake = FakeOpenSearch()
    store = OpenSearchLogStore(fake)
    fake_bulk = MagicMock(return_value=(2, []))
    fake_helpers = ModuleType("opensearchpy.helpers")
    fake_helpers.bulk = fake_bulk
    fake_parent = ModuleType("opensearchpy")
    fake_parent.helpers = fake_helpers
    monkeypatch.setitem(sys.modules, "opensearchpy", fake_parent)
    monkeypatch.setitem(sys.modules, "opensearchpy.helpers", fake_helpers)
    store.write_logs([("1", make_log()), ("2", make_log("ERROR"))])
    assert fake_bulk.call_count == 1
    actions = list(fake_bulk.call_args.args[1])
    assert len(actions) == 2 and all("_index" in x and "_id" in x for x in actions)
    fake_bulk.return_value = (1, [{"index": {"error": "unavailable"}}])
    with pytest.raises(StorageError):
        store.write_logs([("1", make_log()), ("2", make_log())])


def test_legacy_mode_supports_retention_rollback():
    fake = FakeOpenSearch()
    fake.delete_by_query = MagicMock(return_value={"deleted": 3})
    store = OpenSearchLogStore(fake, daily_index=False)
    assert store.delete_older_than("2026-10-01T00:00:00+00:00") == 3
    assert fake.delete_by_query.call_args.kwargs["index"] == "logs"
