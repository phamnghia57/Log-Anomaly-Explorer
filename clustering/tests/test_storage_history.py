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


def test_list_history_loc_theo_cluster_id_va_sap_tang_dan(store):
    s, client = store
    points = s.list_history("c1")

    assert points == [{"cluster_id": "c1", "score": 2.0, "status": "anomalous",
                        "recorded_at": "2026-10-24T00:00:00+00:00"}]
    body = client.calls[-1][1]["body"]
    assert {"term": {"cluster_id": "c1"}} in body["query"]["bool"]["filter"]
    assert body["sort"] == [{"recorded_at": "asc"}]


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
