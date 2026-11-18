"""Test cho phan doc cua cluster-history-schema.json (Nghia, chuan bi truoc
phan ghi cua Nam). Dung FakeClient gia (khong can OpenSearch that), cung kieu
voi ingestion/tests/test_ingestion.py::FakeClient.
"""
import pytest

from ingestion.src.storage import OpenSearchLogStore
from clustering.src.storage import OpenSearchStore, StorageError


class FakeIndices:
    def __init__(self):
        self.created = {}

    def exists(self, index):
        return index in self.created

    def create(self, index, body):
        self.created[index] = body

    def put_mapping(self, index, body):
        self.created[index]["mappings"]["properties"].update(body["properties"])


class FakeClient:
    def __init__(self):
        self.indices = FakeIndices()
        self.calls = []

    def search(self, **kw):
        self.calls.append(("search", kw))
        return {"hits": {"hits": [
            {"_source": {"cluster_id": "c1", "score": 2.0, "status": "anomalous",
                          "recorded_at": "2026-10-24T00:00:00+00:00"}},
        ]}}

    def ping(self):
        return True


@pytest.fixture()
def store():
    client = FakeClient()
    s = OpenSearchStore(log_store=OpenSearchLogStore(client))
    s.ensure_ready()
    return s, client


def test_ensure_ready_tao_index_history_voi_mapping_strict(store):
    s, client = store
    assert "cluster-history" in client.indices.created
    mapping = client.indices.created["cluster-history"]["mappings"]
    assert mapping["dynamic"] == "strict"
    assert mapping["properties"]["cluster_id"]["type"] == "keyword"
    assert mapping["properties"]["score"]["type"] == "double"
    assert mapping["properties"]["recorded_at"]["type"] == "date"


def test_heartbeat_mapping_migration_and_metrics(store):
    s, client = store
    client.indices.created[s.heartbeat]["mappings"]["properties"] = {"last_processed_at": {"type": "date"}}
    s.ensure_ready()
    fields = client.indices.created[s.heartbeat]["mappings"]["properties"]
    assert fields["cycle_seconds"] == {"type": "double"}
    assert fields["logs_read"] == fields["clusters_out"] == {"type": "long"}
    client.index = lambda **kw: client.calls.append(("index", kw))
    s.write_heartbeat("2026-10-26T00:00:00Z", cycle_seconds=12.5, logs_read=100, clusters_out=3)
    assert client.calls[-1][1]["body"] == {"last_processed_at": "2026-10-26T00:00:00Z",
                                             "cycle_seconds": 12.5, "logs_read": 100, "clusters_out": 3}


def test_history_retention_deletes_only_points_before_cutoff(store):
    s, client = store
    calls = []
    def delete_by_query(**kwargs):
        calls.append(kwargs)
        return {"deleted": 2, "timed_out": False, "failures": [], "version_conflicts": 0}
    client.delete_by_query = delete_by_query
    assert s.delete_history_before("2026-10-01T00:00:00+00:00") == 2
    assert calls == [{"index": "cluster-history", "body": {"query": {"range": {
        "recorded_at": {"lt": "2026-10-01T00:00:00+00:00"}}}}, "conflicts": "proceed", "refresh": False}]


@pytest.mark.parametrize("response", [{"deleted": 0, "timed_out": True},
                                      {"deleted": 1, "failures": [{"cause": "error"}]},
                                      {"deleted": 1, "version_conflicts": 1}])
def test_history_retention_reports_incomplete_delete(store, response):
    s, client = store
    client.delete_by_query = lambda **kw: response
    with pytest.raises(StorageError, match="retention failed"):
        s.delete_history_before("2026-10-01T00:00:00Z")


def test_history_retention_rejects_index_patterns(store):
    s, client = store
    s.history = "*"
    client.delete_by_query = lambda **kw: pytest.fail("must not issue broad deletion")
    with pytest.raises(StorageError, match="explicit index"):
        s.delete_history_before("2026-10-01T00:00:00Z")


def test_alert_state_batch_roundtrip_across_store_instances(store):
    s, client = store
    documents = {}
    def bulk(*, body):
        for action, record in zip(body[::2], body[1::2]):
            assert action["index"]["_index"] == s.alert_state
            documents[action["index"]["_id"]] = record
        return {"errors": False}
    def mget(*, index, body):
        assert index == s.alert_state
        return {"docs": [{"_id": key, "found": key in documents,
                          "_source": documents.get(key)} for key in body["ids"]]}
    client.bulk, client.mget = bulk, mget
    s.write_alert_times(["c1", "c2"], 1234.5)
    restarted = OpenSearchStore(log_store=OpenSearchLogStore(client))
    assert restarted.get_alert_times(["c1", "c2", "missing"]) == {"c1": 1234.5, "c2": 1234.5}
    assert client.indices.created[s.alert_state]["mappings"]["properties"] == {"sent_at": {"type": "double"}}


@pytest.mark.parametrize("operation", ["read", "write"])
def test_alert_state_rejects_partial_failures(store, operation):
    s, client = store
    client.mget = lambda **kw: {"docs": [{"error": "unavailable"}]}
    client.bulk = lambda **kw: {"errors": True}
    with pytest.raises(StorageError):
        if operation == "read":
            s.get_alert_times(["c1"])
        else:
            s.write_alert_times(["c1"], 1234)


def test_list_history_loc_theo_cluster_id_va_sap_tang_dan(store):
    s, client = store
    points = s.list_history("c1")

    assert points == [{"cluster_id": "c1", "score": 2.0, "status": "anomalous",
                        "recorded_at": "2026-10-24T00:00:00+00:00"}]
    body = client.calls[-1][1]["body"]
    assert {"term": {"cluster_id": "c1"}} in body["query"]["bool"]["filter"]
    assert body["sort"] == [{"recorded_at": "desc"}]


def test_list_history_lay_diem_moi_nhat_va_tra_theo_thoi_gian(store):
    s, client = store
    records = [
        {"cluster_id": "c1", "score": n, "status": "normal",
         "recorded_at": f"2026-10-{n:02d}T00:00:00Z"}
        for n in range(1, 6)
    ]

    def search(**kw):
        body = kw["body"]
        assert body["sort"] == [{"recorded_at": "desc"}]
        assert body["size"] == 3
        return {"hits": {"hits": [{"_source": point} for point in
                                   sorted(records, key=lambda p: p["recorded_at"], reverse=True)[:body["size"]]]}}

    client.search = search
    assert [point["score"] for point in s.list_history("c1", limit=3)] == [3, 4, 5]


def test_list_history_co_since_them_filter_range(store):
    s, client = store
    s.list_history("c1", since="2026-10-01T00:00:00+00:00", limit=50)

    body = client.calls[-1][1]["body"]
    assert {"range": {"recorded_at": {"gte": "2026-10-01T00:00:00+00:00"}}} in body["query"]["bool"]["filter"]
    assert body["size"] == 50


def test_list_history_limit_khong_hop_le_nem_value_error(store):
    s, _ = store
    with pytest.raises(ValueError):
        s.list_history("c1", limit=0)


def test_list_history_loi_client_boc_thanh_storage_error(store):
    s, client = store

    def boom(**_kw):
        raise RuntimeError("conn refused")

    client.search = boom
    with pytest.raises(StorageError):
        s.list_history("c1")


def test_write_history_appends_only_schema_fields(store):
    s, client = store
    client.index = lambda **kw: client.calls.append(("index", kw))
    record = {"cluster_id": "c1", "score": 5.0, "status": "alerted", "log_ids": ["private"]}
    for end in ("2026-10-26T00:01:00Z", "2026-10-26T00:02:00Z"):
        s.write_history(record, end)
    assert len(client.calls) == 2
    for _, call in client.calls:
        assert call["index"] == "cluster-history"
        assert "id" not in call
        assert set(call["body"]) == {"cluster_id", "score", "status", "recorded_at"}
        assert call["body"]["status"] == "alerted"
    assert client.calls[0][1]["body"]["recorded_at"] != client.calls[1][1]["body"]["recorded_at"]


def test_write_history_wraps_client_failure(store):
    s, client = store
    def fail(**kw):
        raise RuntimeError("offline")
    client.index = fail
    with pytest.raises(StorageError, match="write_history failed"):
        s.write_history({"cluster_id": "c1", "score": 1, "status": "normal"}, "2026-10-26T00:01:00Z")
