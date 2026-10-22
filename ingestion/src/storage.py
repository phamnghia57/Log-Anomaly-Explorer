"""
Storage client cho log da chuan hoa.

Engine duoc chon: OpenSearch (phu hop Search full-text + loc nhieu truong).

Interface `LogStore` giu on dinh de clustering (Nam) va query-api (Nghia)
khong bi anh huong. Cac phuong thuc moi (`search_with_total`, `get_logs`) chi la
bo sung, khong doi chu ky cua phuong thuc cu.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class StorageError(Exception):
    """Kho du lieu khong truy cap duoc / tra loi loi."""


class LogStore:
    """Interface luu & truy van log. Cai dat cu the trong lop con."""

    def write_log(self, log_id: str, log: dict) -> None:
        raise NotImplementedError

    def write_quarantine(self, log: dict, errors: list[str]) -> None:
        """Log sai schema - luu rieng, KHONG vao index chinh (xem docs/architect/contracts/api-contract.md)."""
        raise NotImplementedError

    def search(self, *, service: str | None = None, trace_id: str | None = None,
               query: str | None = None, time_from: str | None = None,
               time_to: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        """Dung boi Nghia (GET /search). Tra ve log moi nhat truoc.

        Moi log tra ve co them truong `log_id` (gan luc DOC, khong luu o write_log)."""
        raise NotImplementedError

    def search_with_total(self, **filters: Any) -> tuple[list[dict], int]:
        """Nhu `search` nhung kem tong so ban ghi khop (khong bi cat boi limit)."""
        hits = self.search(**filters)
        return hits, len(hits)

    def get_logs(self, log_ids: list[str]) -> list[dict]:
        """Tra log thô theo `log_ids` (Nam: cluster-record; Nghia: Incident View).

        Moi log tra ve co them truong `log_id` (gan luc DOC, khong luu o write_log)."""
        raise NotImplementedError

    def delete_older_than(self, cutoff_iso: str) -> int:
        """Dung boi retention job (xem retention.py). Tra ve so log da xoa."""
        raise NotImplementedError

    def ping(self) -> bool:
        return True

    def ensure_ready(self) -> None:
        """Tao index/mapping neu chua co. Goi 1 lan luc khoi dong."""


# --------------------------------------------------------------------------- OpenSearch

# Mapping cho StructuredLog (docs/architect/contracts/log-schema.json).
# - id/field loc chinh xac -> keyword
# - message/stack_trace -> text (full-text) ; message co them .raw keyword
# - metadata: luu trong _source nhung KHONG index (dynamic=false) de tranh no mapping.
LOG_MAPPING: dict = {
    "dynamic": "strict",
    "properties": {
        "timestamp": {"type": "date"},
        "level": {"type": "keyword"},
        "service": {"type": "keyword"},
        "trace_id": {"type": "keyword"},
        "span_id": {"type": "keyword"},
        "request_id": {"type": "keyword"},
        "message": {
            "type": "text",
            "fields": {"raw": {"type": "keyword", "ignore_above": 512}},
        },
        "stack_trace": {"type": "text"},
        "metadata": {"type": "object", "dynamic": False},
    },
}

QUARANTINE_MAPPING: dict = {
    "dynamic": "strict",
    "properties": {
        "received_at": {"type": "date"},
        "errors": {"type": "text"},
        # Payload sai schema co the co bat ky kieu -> chi luu, khong index.
        "log": {"type": "object", "enabled": False},
    },
}


def _with_log_id(log: dict, log_id: str) -> dict:
    """Ban sao cua `log` kem `log_id` - chi gan luc DOC, khong sua dict goc / document da luu."""
    return {**log, "log_id": log_id}


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenSearchLogStore(LogStore):
    def __init__(self, client: Any, *, log_index: str = "logs",
                 quarantine_index: str = "logs-quarantine",
                 shards: int = 1, replicas: int = 0) -> None:
        self.client = client
        self.log_index = log_index
        self.quarantine_index = quarantine_index
        self.shards = shards
        self.replicas = replicas

    # -- khoi tao
    @classmethod
    def from_config(cls) -> "OpenSearchLogStore":
        from opensearchpy import OpenSearch

        from . import config

        kwargs: dict = dict(
            hosts=[config.OPENSEARCH_URL],
            timeout=config.OPENSEARCH_TIMEOUT,
            verify_certs=config.OPENSEARCH_VERIFY_CERTS,
            ssl_show_warn=False,
            max_retries=2,
            retry_on_timeout=True,
        )
        if config.OPENSEARCH_USER:
            kwargs["http_auth"] = (config.OPENSEARCH_USER, config.OPENSEARCH_PASSWORD)
        return cls(
            OpenSearch(**kwargs),
            log_index=config.LOG_INDEX,
            quarantine_index=config.QUARANTINE_INDEX,
            shards=config.NUMBER_OF_SHARDS,
            replicas=config.NUMBER_OF_REPLICAS,
        )

    def _settings(self) -> dict:
        return {"index": {"number_of_shards": self.shards, "number_of_replicas": self.replicas}}

    def ensure_ready(self) -> None:
        for name, mapping in ((self.log_index, LOG_MAPPING), (self.quarantine_index, QUARANTINE_MAPPING)):
            try:
                if not self.client.indices.exists(index=name):
                    self.client.indices.create(
                        index=name, body={"settings": self._settings(), "mappings": mapping}
                    )
            except Exception as exc:  # noqa: BLE001
                # Race giua 2 worker cung tao index -> bo qua neu da ton tai
                if "resource_already_exists_exception" in str(exc):
                    continue
                raise StorageError(f"cannot prepare index {name}: {exc}") from exc

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:  # noqa: BLE001
            return False

    # -- ghi
    def write_log(self, log_id: str, log: dict) -> None:
        try:
            # op_type=index: cung log_id thi ghi de -> idempotent khi client retry
            self.client.index(index=self.log_index, id=log_id, body=log)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"write_log failed: {exc}") from exc

    def write_quarantine(self, log: dict, errors: list[str]) -> None:
        try:
            self.client.index(
                index=self.quarantine_index,
                body={"received_at": _iso_utc_now(), "errors": errors, "log": log},
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"write_quarantine failed: {exc}") from exc

    # -- doc
    @staticmethod
    def _build_query(service: str | None, trace_id: str | None, query: str | None,
                     time_from: str | None, time_to: str | None) -> dict:
        must: list[dict] = []
        filters: list[dict] = []
        if service:
            filters.append({"term": {"service": service}})
        if trace_id:
            filters.append({"term": {"trace_id": trace_id}})
        if time_from or time_to:
            rng: dict = {}
            if time_from:
                rng["gte"] = time_from
            if time_to:
                rng["lte"] = time_to
            filters.append({"range": {"timestamp": rng}})
        if query:
            must.append({"match": {"message": {"query": query, "operator": "and"}}})
        if not must and not filters:
            return {"match_all": {}}
        return {"bool": {"must": must, "filter": filters}}

    def search_with_total(self, *, service: str | None = None, trace_id: str | None = None,
                          query: str | None = None, time_from: str | None = None,
                          time_to: str | None = None, limit: int = 100,
                          offset: int = 0) -> tuple[list[dict], int]:
        body = {
            "query": self._build_query(service, trace_id, query, time_from, time_to),
            "sort": [{"timestamp": {"order": "desc"}}],
            "from": offset,
            "size": limit,
            "track_total_hits": True,
        }
        try:
            resp = self.client.search(index=self.log_index, body=body)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"search failed: {exc}") from exc
        total = resp["hits"]["total"]
        total = total["value"] if isinstance(total, dict) else int(total)
        return [_with_log_id(h["_source"], h["_id"]) for h in resp["hits"]["hits"]], total

    def search(self, **filters: Any) -> list[dict]:
        return self.search_with_total(**filters)[0]

    def get_logs(self, log_ids: list[str]) -> list[dict]:
        if not log_ids:
            return []
        try:
            resp = self.client.mget(index=self.log_index, body={"ids": list(log_ids)})
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"get_logs failed: {exc}") from exc
        return [_with_log_id(d["_source"], d["_id"]) for d in resp["docs"] if d.get("found")]

    def delete_older_than(self, cutoff_iso: str) -> int:
        try:
            resp = self.client.delete_by_query(
                index=self.log_index,
                body={"query": {"range": {"timestamp": {"lt": cutoff_iso}}}},
                conflicts="proceed",
                refresh=True,
                wait_for_completion=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"delete_older_than failed: {exc}") from exc
        return int(resp.get("deleted", 0))


# --------------------------------------------------------------------------- In-memory (dev/test)

class InMemoryLogStore(LogStore):
    """Trien khai tam thoi (khong persist) de dev/test ma khong can OpenSearch that."""

    def __init__(self) -> None:
        self._logs: dict[str, dict] = {}
        self._quarantine: list[dict] = []

    def write_log(self, log_id: str, log: dict) -> None:
        self._logs[log_id] = log

    def write_quarantine(self, log: dict, errors: list[str]) -> None:
        self._quarantine.append({"received_at": _iso_utc_now(), "log": log, "errors": errors})

    @staticmethod
    def _ts(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def search_with_total(self, **filters: Any) -> tuple[list[dict], int]:
        # Gan log_id luc doc (ban sao) - khong sua dict dang luu trong self._logs
        results = [_with_log_id(log, log_id) for log_id, log in self._logs.items()]
        if filters.get("service"):
            results = [l for l in results if l.get("service") == filters["service"]]
        if filters.get("trace_id"):
            results = [l for l in results if l.get("trace_id") == filters["trace_id"]]
        if filters.get("query"):
            words = filters["query"].lower().split()
            results = [l for l in results if all(w in l.get("message", "").lower() for w in words)]
        if filters.get("time_from"):
            lo = self._ts(filters["time_from"])
            results = [l for l in results if self._ts(l["timestamp"]) >= lo]
        if filters.get("time_to"):
            hi = self._ts(filters["time_to"])
            results = [l for l in results if self._ts(l["timestamp"]) <= hi]
        results.sort(key=lambda l: self._ts(l["timestamp"]), reverse=True)
        total = len(results)
        offset = filters.get("offset", 0)
        limit = filters.get("limit", 100)
        return results[offset:offset + limit], total

    def search(self, **filters: Any) -> list[dict]:
        return self.search_with_total(**filters)[0]

    def get_logs(self, log_ids: list[str]) -> list[dict]:
        return [_with_log_id(self._logs[i], i) for i in log_ids if i in self._logs]

    def delete_older_than(self, cutoff_iso: str) -> int:
        cutoff = self._ts(cutoff_iso)
        before = len(self._logs)
        self._logs = {k: v for k, v in self._logs.items() if self._ts(v["timestamp"]) >= cutoff}
        return before - len(self._logs)


def build_store() -> LogStore:
    """Chon store theo STORAGE_BACKEND (mac dinh: opensearch)."""
    from . import config

    if config.STORAGE_BACKEND == "memory":
        return InMemoryLogStore()
    if config.STORAGE_BACKEND == "opensearch":
        return OpenSearchLogStore.from_config()
    raise ValueError(f"STORAGE_BACKEND khong hop le: {config.STORAGE_BACKEND!r}")
