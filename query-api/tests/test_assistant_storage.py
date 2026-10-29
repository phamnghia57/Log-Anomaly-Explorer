"""Test cho ConversationRepository (query-api/src/assistant/storage.py) -
dung FakeClient gia, cung kieu voi
ingestion/tests/test_ingestion.py::FakeClient va
clustering/tests/test_storage_history.py.
"""
from __future__ import annotations

import importlib

import pytest

conversation_storage = importlib.import_module("query-api.src.assistant.storage")
ingestion_storage = importlib.import_module("ingestion.src.storage")


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
        self.docs: dict[str, dict] = {}
        self.calls = []

    def index(self, *, index, id, body, **_kw):
        self.calls.append(("index", {"index": index, "id": id, "body": body}))
        self.docs[id] = body

    def get(self, *, index, id, **_kw):
        self.calls.append(("get", {"index": index, "id": id}))
        if id in self.docs:
            return {"found": True, "_source": self.docs[id]}
        return {"found": False}


@pytest.fixture()
def repo():
    client = FakeClient()
    log_store = ingestion_storage.OpenSearchLogStore(client)
    repository = conversation_storage.ConversationRepository(log_store)
    repository.ensure_ready()
    return repository, client


def test_ensure_ready_tao_index_voi_mapping_strict(repo):
    _repository, client = repo
    assert "assistant-conversations" in client.indices.created
    mapping = client.indices.created["assistant-conversations"]["mappings"]
    assert mapping["dynamic"] == "strict"
    assert mapping["properties"]["cluster_id"]["type"] == "keyword"
    assert mapping["properties"]["messages"] == {"type": "object", "dynamic": False}


def test_get_chua_co_conversation_tra_none(repo):
    repository, _client = repo
    assert repository.get("khong-ton-tai") is None


def test_save_roi_get_lai_dung_du_lieu(repo):
    repository, client = repo
    messages = [{"role": "user", "content": "hi", "created_at": "2026-10-29T00:00:00+00:00"}]

    saved = repository.save("c1", messages)

    assert saved["cluster_id"] == "c1"
    assert saved["messages"] == messages
    assert saved["created_at"] == saved["updated_at"]  # lan dau: created == updated
    assert client.docs["c1"] == saved  # upsert dung _id = cluster_id

    fetched = repository.get("c1")
    assert fetched == saved


def test_save_lan_2_giu_nguyen_created_at_ban_dau(repo):
    repository, _client = repo
    first = repository.save("c1", [], created_at=None)
    second = repository.save("c1", [{"role": "user", "content": "more", "created_at": "x"}],
                             created_at=first["created_at"])

    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]


def test_ensure_ready_goi_lai_khong_nem_loi(repo):
    repository, client = repo
    # Index da ton tai tu fixture (ensure_ready da chay 1 lan) - indices.exists()
    # tra True nen lan nay bo qua create() hoan toan (idempotent).
    repository.ensure_ready()
    assert "assistant-conversations" in client.indices.created


def test_ensure_ready_bo_qua_loi_index_da_ton_tai_tu_worker_khac(repo):
    """Race giua 2 worker cung tao index: client.create() nem loi du
    indices.exists() vua tra False (worker kia tao xong truoc). Phai bo qua
    loi nay, khong duoc nem StorageError."""
    repository, client = repo

    def boom(*, index, body):
        raise RuntimeError("resource_already_exists_exception: index da ton tai")

    client.indices.exists = lambda index: False
    client.indices.create = boom

    repository.ensure_ready()  # khong duoc nem loi
