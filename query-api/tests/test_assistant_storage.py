"""ConversationRepository regression tests using the versioned OpenSearch double."""
from __future__ import annotations

import importlib

import pytest
from opensearchpy.exceptions import RequestError

from vt013_opensearch_fake import RevisionedOpenSearch

conversation_storage = importlib.import_module("query-api.src.assistant.storage")
ingestion_storage = importlib.import_module("ingestion.src.storage")


@pytest.fixture()
def repo():
    client = RevisionedOpenSearch()
    log_store = ingestion_storage.OpenSearchLogStore(client)
    repository = conversation_storage.ConversationRepository(log_store)
    repository.ensure_ready()
    return repository, client


def test_ensure_ready_tao_index_voi_mapping_strict(repo):
    _repository, client = repo
    assert "assistant-conversations" in client.mappings
    mapping = client.mappings["assistant-conversations"]["mappings"]
    assert mapping["dynamic"] == "strict"
    assert mapping["properties"]["cluster_id"]["type"] == "keyword"
    assert mapping["properties"]["messages"] == {"type": "object", "dynamic": False}
    assert mapping["properties"]["undo"] == {"type": "object", "enabled": False}


def test_get_chua_co_conversation_tra_none(repo):
    repository, _client = repo
    assert repository.get("khong-ton-tai") is None


def test_save_roi_get_lai_dung_du_lieu(repo):
    repository, client = repo
    messages = [{"role": "user", "content": "hi", "created_at": "2026-10-29T00:00:00+00:00"}]

    saved = repository.save("c1", messages, previous=None)

    assert saved.document["cluster_id"] == "c1"
    assert saved.document["messages"] == messages
    assert saved.document["created_at"] == saved.document["updated_at"]
    assert client.snapshot(index=repository.index, id="c1")["_source"] == saved.document
    assert saved.revision == "1:0"

    fetched = repository.get("c1")
    assert fetched == saved


def test_save_lan_2_giu_nguyen_created_at_ban_dau(repo):
    repository, _client = repo
    first = repository.save("c1", [], previous=None)
    second = repository.save("c1", [{"role": "user", "content": "more",
                                    "created_at": "2026-10-29T00:00:00+00:00"}],
                             previous=first)

    assert second.document["created_at"] == first.document["created_at"]
    assert second.document["updated_at"] >= first.document["updated_at"]
    assert second.seq_no > first.seq_no


def test_ensure_ready_goi_lai_khong_nem_loi(repo):
    repository, client = repo
    # Existing indexes receive an additive, idempotent snapshot mapping update.
    repository.ensure_ready()
    assert "assistant-conversations" in client.mappings


def test_ensure_ready_bo_qua_loi_index_da_ton_tai_tu_worker_khac(repo):
    """Race giua 2 worker cung tao index: client.create() nem loi du
    indices.exists() vua tra False (worker kia tao xong truoc). Phai bo qua
    loi nay, khong duoc nem StorageError."""
    repository, client = repo

    def boom(*, index, body):
        raise RequestError(400, "resource_already_exists_exception", {})

    client.indices.exists = lambda index: False
    client.indices.create = boom

    repository.ensure_ready()  # khong duoc nem loi
