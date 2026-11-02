from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ingestion.src import main
from ingestion.src.retention import run_retention
from ingestion.src.storage import InMemoryLogStore, OpenSearchLogStore, StorageError
from ingestion.src.validator import validate_log


def iso(delta_hours=0):
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_log(**over):
    log = {"timestamp": iso(), "level": "ERROR", "service": "demo-web",
           "trace_id": "t1", "span_id": "s1", "message": "Simulated failure in checkout"}
    log.update(over)
    return log


@pytest.fixture
def client():
    main.store = InMemoryLogStore()
    main.limiter = main.SlidingWindowRateLimiter(1000)
    with TestClient(main.app) as c:
        yield c


# ---- API
def test_ingest_valid_returns_202(client):
    r = client.post("/ingest", json=make_log())
    assert r.status_code == 202
    assert r.json()["accepted"] is True and r.json()["log_id"]


def test_ingest_invalid_returns_400_and_quarantines(client):
    r = client.post("/ingest", json={"level": "ERROR"})
    assert r.status_code == 400
    body = r.json()
    assert body["accepted"] is False and body["reason"] == "schema_validation_failed"
    assert len(main.store._quarantine) == 1
    assert client.get("/search").json()["total"] == 0  # khong vao index chinh


def test_bad_timestamp_and_extra_field_rejected(client):
    assert client.post("/ingest", json=make_log(timestamp="yesterday")).status_code == 400
    assert client.post("/ingest", json=make_log(timestamp="2026-10-01T09:00:00")).status_code == 400
    assert client.post("/ingest", json=make_log(foo=1)).status_code == 400


def test_search_filters_and_default_window(client):
    client.post("/ingest", json=make_log(trace_id="a", message="db timeout"))
    client.post("/ingest", json=make_log(trace_id="b", service="other", message="ok done"))
    client.post("/ingest", json=make_log(trace_id="old", timestamp=iso(-72)))
    assert client.get("/search").json()["total"] == 2          # mac dinh 24h
    assert client.get("/search", params={"trace_id": "a"}).json()["total"] == 1
    assert client.get("/search", params={"service": "other"}).json()["total"] == 1
    assert client.get("/search", params={"q": "timeout"}).json()["total"] == 1
    r = client.get("/search", params={"from": iso(-100), "to": iso(1)})
    assert r.json()["total"] == 3
    assert client.get("/search", params={"from": "garbage"}).status_code == 400


def test_search_pagination_total_not_truncated(client):
    for i in range(5):
        client.post("/ingest", json=make_log(trace_id=f"t{i}"))
    body = client.get("/search", params={"limit": 2}).json()
    assert body["total"] == 5 and len(body["results"]) == 2


def test_storage_error_returns_503(client, monkeypatch):
    def boom(*a, **k):
        raise StorageError("down")
    monkeypatch.setattr(main.store, "write_log", boom)
    r = client.post("/ingest", json=make_log())
    assert r.status_code == 503


def test_retention_deletes_old(client):
    client.post("/ingest", json=make_log(timestamp=iso(-24 * 40)))
    client.post("/ingest", json=make_log())
    assert run_retention(main.store, retention_days=30) == 1
    assert client.get("/search", params={"from": iso(-24 * 50)}).json()["total"] == 1


def test_get_logs_by_ids():
    s = InMemoryLogStore()
    s.write_log("x", make_log())
    got = s.get_logs(["x", "missing"])
    assert len(got) == 1 and got[0]["log_id"] == "x"


def test_inmemory_log_id_attached_on_read_not_on_write():
    s = InMemoryLogStore()
    s.write_log("x", make_log())
    assert "log_id" not in s._logs["x"]  # khong gan luc ghi
    assert s.search()[0]["log_id"] == "x"
    hits, _ = s.search_with_total()
    assert hits[0]["log_id"] == "x"
    assert s.get_logs(["x"])[0]["log_id"] == "x"
    assert "log_id" not in s._logs["x"]  # doc xong van khong ban document goc


def test_validator_ok():
    assert validate_log(make_log()) == []


# ---- OpenSearchLogStore voi client gia (kiem tra request gui di)
class FakeIndices:
    def __init__(self): self.created = {}
    def exists(self, index): return index in self.created
    def create(self, index, body): self.created[index] = body
    def get(self, index, **kw):
        return {name: body for name, body in self.created.items()
                if name.startswith("logs-") and name != "logs-quarantine"}
    def delete(self, index): self.created.pop(index); return {"acknowledged": True}


class FakeClient:
    def __init__(self):
        self.indices = FakeIndices(); self.calls = []
    def index(self, **kw): self.calls.append(("index", kw))
    def search(self, **kw):
        self.calls.append(("search", kw))
        if "aggs" in kw["body"]:
            return {"aggregations": {
                "histogram": {"buckets": [{"key_as_string": "2026-10-01T00:00:00.000Z", "doc_count": 2}]},
                "levels": {"buckets": [{"key": "ERROR", "doc_count": 2}]},
                "services": {"buckets": [{"key": "demo-web", "doc_count": 2}]},
            }}
        return {"hits": {"total": {"value": 7}, "hits": [{"_id": "h1", "_source": {"message": "m"}}]}}
    def mget(self, **kw):
        self.calls.append(("mget", kw))
        return {"docs": [{"_id": "a", "found": True, "_source": {"a": 1}}, {"_id": "b", "found": False}]}
    def delete_by_query(self, **kw):
        self.calls.append(("dbq", kw)); return {"deleted": 3}
    def bulk(self, **kw):
        self.calls.append(("bulk", kw)); return {"errors": False, "items": []}
    def ping(self): return True


def test_opensearch_store_requests():
    c = FakeClient()
    s = OpenSearchLogStore(c)
    s.ensure_ready()
    assert set(c.indices.created) == {"logs-quarantine"}  # logs legacy khong tao nua

    s.write_log("id1", make_log(timestamp="2026-10-01T23:50:00+07:00"))
    assert c.calls[-1][1]["id"] == "id1" and c.calls[-1][1]["index"] == "logs-2026.10.01"
    assert c.indices.created["logs-2026.10.01"]["mappings"]["properties"]["level"]["type"] == "keyword"
    s.write_quarantine({"bad": 1}, ["e"])
    assert c.calls[-1][1]["index"] == "logs-quarantine"

    hits, total = s.search_with_total(service="a", trace_id="t", query="boom",
                                      time_from="2026-01-01T00:00:00+00:00", limit=10)
    assert (hits, total) == ([{"message": "m", "log_id": "h1"}], 7)
    body = c.calls[-1][1]["body"]
    assert {"term": {"service": "a"}} in body["query"]["bool"]["filter"]
    assert {"term": {"trace_id": "t"}} in body["query"]["bool"]["filter"]
    assert body["sort"] == [{"timestamp": {"order": "desc"}}] and body["size"] == 10

    assert s.get_logs(["h1", "missing"]) == [{"message": "m", "log_id": "h1"}]
    assert c.calls[-1][1]["body"]["query"]["ids"]["values"] == ["h1", "missing"]
    # write_log khong gan log_id vao body da ghi
    s.write_log("id2", make_log())
    assert "log_id" not in c.calls[-1][1]["body"]
    s.write_logs_batch([("batch1", make_log(timestamp="2026-10-01T00:00:00Z")),
                        ("batch2", make_log(timestamp="2026-10-02T00:00:00Z"))])
    assert c.calls[-1][0] == "bulk" and len(c.calls[-1][1]["body"]) == 4
    assert s.delete_older_than("2026-10-02T12:00:00Z") == 1
    assert "logs-2026.10.01" not in c.indices.created
    assert "logs-quarantine" in c.indices.created  # khong drop quarantine
    assert all(call[0] != "dbq" for call in c.calls)


def test_opensearch_errors_wrapped():
    class Bad(FakeClient):
        def index(self, **kw): raise RuntimeError("conn refused")
    with pytest.raises(StorageError):
        OpenSearchLogStore(Bad()).write_log("i", make_log())


# ---- Batch + rate limiting

def test_batch_writes_many_logs(client):
    r = client.post("/ingest/batch", json=[make_log(trace_id="a"), make_log(trace_id="b")])
    assert r.status_code == 202
    assert r.json()["accepted_count"] == 2
    assert len(set(r.json()["log_ids"])) == 2
    assert client.get("/search").json()["total"] == 2


def test_batch_rejects_all_when_any_invalid_and_quarantines(client):
    r = client.post("/ingest/batch", json=[make_log(), {"message": "bad"}])
    assert r.status_code == 400
    assert r.json()["errors"][0]["index"] == 1
    assert len(main.store._quarantine) == 1
    assert client.get("/search").json()["total"] == 0


def test_batch_validation_and_size_limit(client, monkeypatch):
    assert client.post("/ingest/batch", json={"message": "not a list"}).status_code == 422
    assert client.post("/ingest/batch", json=[]).status_code == 400
    assert client.post("/ingest/batch", json=[42]).status_code == 422
    monkeypatch.setattr(main.config, "INGEST_MAX_BATCH_SIZE", 1)
    assert client.post("/ingest/batch", json=[make_log(), make_log()]).status_code == 400


def test_rate_limit_shared_by_both_ingest_routes(client):
    main.limiter = main.SlidingWindowRateLimiter(2)
    assert client.post("/ingest", json=make_log()).status_code == 202
    assert client.post("/ingest/batch", json=[make_log()]).status_code == 202
    blocked = client.post("/ingest", json=make_log())
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "1"
    assert client.get("/health").status_code == 200


def test_search_level_and_histogram_inmemory(client):
    client.post("/ingest/batch", json=[make_log(level="ERROR"), make_log(level="INFO")])
    assert client.get("/search", params={"level": "ERROR"}).json()["total"] == 1
    assert client.get("/search", params={"level": "BROKEN"}).status_code == 422
    r = client.get("/search/aggregations")
    assert r.status_code == 200
    assert sum(p["count"] for p in r.json()["histogram"]) == 2
    assert {b["key"] for b in r.json()["levels"]} == {"INFO", "ERROR"}
    assert sum(p["count"] for p in client.get("/search/aggregations", params={"level": "ERROR"}).json()["histogram"]) == 1


def test_opensearch_filter_and_histogram_request():
    client = FakeClient()
    store = OpenSearchLogStore(client)
    store.search_with_total(level="ERROR")
    sent = client.calls[-1][1]
    assert {"term": {"level": "ERROR"}} in sent["body"]["query"]["bool"]["filter"]
    assert sent["index"] == "logs,logs-????.??.??"
    assert "logs-quarantine" not in sent["index"]
    aggs = store.aggregate_logs(level="ERROR", interval="day")
    assert aggs["levels"] == [{"key": "ERROR", "count": 2}]
    assert client.calls[-1][1]["body"]["aggs"]["histogram"]["date_histogram"]["fixed_interval"] == "1d"


def test_daily_index_cutoff_does_not_drop_partial_day():
    client = FakeClient()
    store = OpenSearchLogStore(client)
    store.write_log("prev", make_log(timestamp="2026-10-01T23:59:00Z"))
    store.write_log("same", make_log(timestamp="2026-10-02T00:10:00Z"))
    assert store.delete_older_than("2026-10-02T10:00:00Z") == 1
    assert "logs-2026.10.02" in client.indices.created


def test_bulk_failure_is_not_silenced():
    class FailingBulk(FakeClient):
        def bulk(self, **kw): return {"errors": True, "items": [{"index": {"status": 503}}]}
    with pytest.raises(StorageError, match="partially failed"):
        OpenSearchLogStore(FailingBulk()).write_logs_batch([("x", make_log())])
