from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src import main
from src.retention import run_retention
from src.storage import InMemoryLogStore, OpenSearchLogStore, StorageError
from src.validator import validate_log


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
    assert len(s.get_logs(["x", "missing"])) == 1


def test_validator_ok():
    assert validate_log(make_log()) == []


# ---- OpenSearchLogStore voi client gia (kiem tra request gui di)
class FakeIndices:
    def __init__(self): self.created = {}
    def exists(self, index): return index in self.created
    def create(self, index, body): self.created[index] = body


class FakeClient:
    def __init__(self):
        self.indices = FakeIndices(); self.calls = []
    def index(self, **kw): self.calls.append(("index", kw))
    def search(self, **kw):
        self.calls.append(("search", kw))
        return {"hits": {"total": {"value": 7}, "hits": [{"_source": {"message": "m"}}]}}
    def mget(self, **kw):
        self.calls.append(("mget", kw))
        return {"docs": [{"found": True, "_source": {"a": 1}}, {"found": False}]}
    def delete_by_query(self, **kw):
        self.calls.append(("dbq", kw)); return {"deleted": 3}
    def ping(self): return True


def test_opensearch_store_requests():
    c = FakeClient()
    s = OpenSearchLogStore(c)
    s.ensure_ready()
    assert set(c.indices.created) == {"logs", "logs-quarantine"}
    assert c.indices.created["logs"]["mappings"]["properties"]["trace_id"]["type"] == "keyword"

    s.write_log("id1", {"message": "x"})
    assert c.calls[-1][1]["id"] == "id1" and c.calls[-1][1]["index"] == "logs"
    s.write_quarantine({"bad": 1}, ["e"])
    assert c.calls[-1][1]["index"] == "logs-quarantine"

    hits, total = s.search_with_total(service="a", trace_id="t", query="boom",
                                      time_from="2026-01-01T00:00:00+00:00", limit=10)
    assert (hits, total) == ([{"message": "m"}], 7)
    body = c.calls[-1][1]["body"]
    assert {"term": {"service": "a"}} in body["query"]["bool"]["filter"]
    assert {"term": {"trace_id": "t"}} in body["query"]["bool"]["filter"]
    assert body["sort"] == [{"timestamp": {"order": "desc"}}] and body["size"] == 10

    assert s.get_logs(["a", "b"]) == [{"a": 1}]
    assert s.delete_older_than("2026-01-01T00:00:00+00:00") == 3
    assert c.calls[-1][1]["body"]["query"]["range"]["timestamp"]["lt"].startswith("2026")


def test_opensearch_errors_wrapped():
    class Bad(FakeClient):
        def index(self, **kw): raise RuntimeError("conn refused")
    with pytest.raises(StorageError):
        OpenSearchLogStore(Bad()).write_log("i", {})
