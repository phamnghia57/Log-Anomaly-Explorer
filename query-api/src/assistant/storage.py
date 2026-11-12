"""Luu hoi thoai dieu tra voi AI Assistant, dung chung client OpenSearch da
cau hinh cua ingestion - cung cach query-api/src/users.py (PR Auth, chua
merge) lam cho index `users`.

1 conversation / 1 cluster_id (upsert theo _id = cluster_id, KHONG phai
nhieu thread song song cho cung 1 cum) - xem
docs/architect/contracts/assistant-conversation-schema.json.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ingestion.src.storage import OpenSearchLogStore, StorageError, build_store

from . import config

CONVERSATION_MAPPING = {
    "dynamic": "strict",
    "properties": {
        "cluster_id": {"type": "keyword"},
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
        # object + dynamic=False: luu nguyen (khong index sub-field) - giong
        # cach `metadata` trong log-schema.json xu ly du lieu hinh dang tu
        # do. Khong can tim kiem BEN TRONG noi dung chat, chi can doc lai
        # nguyen ven theo cluster_id.
        "messages": {"type": "object", "dynamic": False},
    },
}


class ConversationRepository:
    def __init__(self, log_store=None):
        self.log_store = log_store if log_store is not None else build_store()
        if not isinstance(self.log_store, OpenSearchLogStore):
            raise ValueError("Assistant conversation storage requires STORAGE_BACKEND=opensearch")
        self.client = self.log_store.client
        self.index = config.CONVERSATIONS_INDEX

    def ensure_ready(self) -> None:
        try:
            if not self.client.indices.exists(index=self.index):
                self.client.indices.create(index=self.index, body={
                    "settings": self.log_store._settings(),
                    "mappings": CONVERSATION_MAPPING,
                })
        except Exception as exc:  # noqa: BLE001
            # Race giua nhieu worker cung tao index - bo qua neu da ton tai.
            if "resource_already_exists_exception" not in str(exc):
                raise StorageError(f"cannot prepare {self.index}: {exc}") from exc

    def get(self, cluster_id: str) -> dict | None:
        """Tra ve conversation hien co cho cluster_id, hoac None neu chua co."""
        try:
            response = self.client.get(index=self.index, id=cluster_id, ignore=[404])
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"get conversation failed: {exc}") from exc
        return response["_source"] if response.get("found") else None

    def save(self, cluster_id: str, messages: list[dict], *, created_at: str | None = None) -> dict:
        """Ghi de toan bo messages (upsert theo cluster_id). `created_at` giu
        nguyen tu lan tao dau neu truyen vao, khong bi reset moi lan luu."""
        now = datetime.now(timezone.utc).isoformat()
        document = {
            "cluster_id": cluster_id,
            "created_at": created_at or now,
            "updated_at": now,
            "messages": messages,
        }
        try:
            # Khong dung refresh="wait_for" (ton ~1s cho refresh interval moi
            # lan luu): `get()` doc theo _id la realtime trong OpenSearch
            # (doc tu translog, khong can refresh) va khong cho nao SEARCH
            # index nay - retention dung delete_by_query voi refresh rieng.
            self.client.index(index=self.index, id=cluster_id, body=document)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"save conversation failed: {exc}") from exc
        return document

    def delete_older_than(self, cutoff_iso: str) -> int:
        """Xoa hoi thoai co `updated_at` < cutoff. Tra ve so hoi thoai da xoa.

        Dung delete_by_query (KHONG tach index theo ngay nhu `logs`): index nay
        chi co toi da 1 document/cum da tung duoc hoi, khoi luong nho hon log
        thuong nhieu bac nen khong can co che drop-index cua ingestion.
        """
        try:
            response = self.client.delete_by_query(
                index=self.index,
                body={"query": {"range": {"updated_at": {"lt": cutoff_iso}}}},
                conflicts="proceed",
                refresh=True,
                wait_for_completion=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"delete_older_than failed: {exc}") from exc
        return int(response.get("deleted", 0))

    def close(self) -> None:
        self.client.close()
