"""Retention cho logs-quarantine (#109): index nay khong bi drop theo ngay va
khong nam trong snapshot, nen delete_by_query theo received_at la tran dia duy
nhat cua no. Khong import main/fastapi: chay duoc chi voi pytest."""

from datetime import datetime, timedelta, timezone

import pytest

from ingestion.src import retention
from ingestion.src.storage import InMemoryLogStore, OpenSearchLogStore, StorageError


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class _Indices:
    def __init__(self, names=()):
        self.created = {n: {} for n in names}
        self.deleted = []

    def exists(self, index):
        return index in self.created

    def get(self, index, **kw):
        prefix = index.rstrip("*")
        return {n: {} for n in self.created if n.startswith(prefix)}

    def delete(self, index):
        self.deleted.append(index)
        self.created.pop(index)


class _Client:
    def __init__(self, names=("logs-quarantine",), dbq_response=None):
        self.indices = _Indices(names)
        self.dbq = []
        self.dbq_response = dbq_response if dbq_response is not None else {"deleted": 5, "failures": []}

    def delete_by_query(self, **kw):
        self.dbq.append(kw)
        return self.dbq_response


def test_opensearch_quarantine_retention_dung_range_received_at():
    client = _Client()
    store = OpenSearchLogStore(client)
    assert store.delete_quarantine_older_than("2026-10-22T00:00:00+00:00") == 5
    call = client.dbq[-1]
    assert call["index"] == "logs-quarantine"
    assert call["body"] == {"query": {"range": {"received_at": {"lt": "2026-10-22T00:00:00+00:00"}}}}
    assert call["conflicts"] == "proceed"


def test_quarantine_retention_khong_dong_vao_index_log():
    client = _Client(names=("logs-quarantine", "logs-2026.10.01", "logs"))
    OpenSearchLogStore(client).delete_quarantine_older_than("2026-10-22T00:00:00+00:00")
    assert [c["index"] for c in client.dbq] == ["logs-quarantine"]
    assert client.indices.deleted == []  # khong drop index nao


def test_quarantine_retention_ten_index_cau_hinh_duoc():
    client = _Client(names=("auth-test-quarantine",))
    store = OpenSearchLogStore(client, quarantine_index="auth-test-quarantine")
    store.delete_quarantine_older_than("2026-10-22T00:00:00+00:00")
    assert client.dbq[-1]["index"] == "auth-test-quarantine"


def test_quarantine_retention_bo_qua_khi_chua_co_index():
    client = _Client(names=())
    assert OpenSearchLogStore(client).delete_quarantine_older_than("2026-10-22T00:00:00+00:00") == 0
    assert client.dbq == []


def test_quarantine_retention_khong_im_lang_khi_failures():
    client = _Client(dbq_response={"deleted": 2, "failures": [{"cause": "version_conflict"}]})
    with pytest.raises(StorageError, match="partially failed"):
        OpenSearchLogStore(client).delete_quarantine_older_than("2026-10-22T00:00:00+00:00")


def test_quarantine_retention_boc_loi_client():
    class Boom(_Client):
        def delete_by_query(self, **kw):
            raise RuntimeError("conn refused")
    with pytest.raises(StorageError, match="quarantine retention failed"):
        OpenSearchLogStore(Boom()).delete_quarantine_older_than("2026-10-22T00:00:00+00:00")


def test_memory_quarantine_retention_xoa_ban_cu_giu_ban_moi():
    store = InMemoryLogStore()
    store._quarantine = [
        {"received_at": _iso(40), "log": {"a": 1}, "errors": ["e"]},
        {"received_at": _iso(31), "log": {"a": 2}, "errors": ["e"]},
        {"received_at": _iso(1), "log": {"a": 3}, "errors": ["e"]},
    ]
    assert retention.run_quarantine_retention(store, retention_days=30) == 2
    assert [q["log"]["a"] for q in store._quarantine] == [3]


def test_run_quarantine_retention_tinh_cutoff_tu_so_ngay():
    seen = {}

    class Spy(InMemoryLogStore):
        def delete_quarantine_older_than(self, cutoff_iso):
            seen["cutoff"] = datetime.fromisoformat(cutoff_iso)
            return 0

    retention.run_quarantine_retention(Spy(), retention_days=7)
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs((seen["cutoff"] - expected).total_seconds()) < 5
    with pytest.raises(ValueError):
        retention.run_quarantine_retention(Spy(), retention_days=0)


def test_run_all_chay_ca_hai_va_loi_mot_phan_khong_chan_phan_kia(monkeypatch):
    calls = []

    class Store(InMemoryLogStore):
        def delete_older_than(self, cutoff_iso):
            calls.append("indices")
            raise StorageError("down")

        def delete_quarantine_older_than(self, cutoff_iso):
            calls.append("quarantine")
            return 4

    with pytest.raises(StorageError):
        retention.run_all(Store())
    assert calls == ["indices", "quarantine"]

    ok = InMemoryLogStore()
    ok._quarantine = [{"received_at": _iso(400), "log": {}, "errors": []}]
    assert retention.run_all(ok) == {"indices": 0, "quarantine_docs": 1}
