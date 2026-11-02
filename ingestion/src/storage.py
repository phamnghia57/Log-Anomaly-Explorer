"""
Storage client cho log da chuan hoa.

Engine duoc chon: OpenSearch (phu hop Search full-text + loc nhieu truong).

Interface `LogStore` giu on dinh de clustering (Nam) va query-api (Nghia)
khong bi anh huong. Cac phuong thuc moi (`search_with_total`, `get_logs`) chi la
bo sung, khong doi chu ky cua phuong thuc cu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import Counter
from typing import Any


class StorageError(Exception):
    """Kho du lieu khong truy cap duoc / tra loi loi."""


class LogStore:
    """Interface luu & truy van log. Cai dat cu the trong lop con."""

    def write_log(self, log_id: str, log: dict) -> None:
        raise NotImplementedError

    def write_logs(self, entries: list[tuple[str, dict]]) -> None:
        """Batch write; implementations may perform partial writes on backend failure."""
        for log_id, log in entries:
            self.write_log(log_id, log)

    def search_with_facets(self, **filters: Any) -> tuple[list[dict], int, dict]:
        results, total = self.search_with_total(**filters)
        return results, total, {"timeline": [], "levels": [], "services": []}

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
        """Retention: daily index mode returns number of dropped indices; memory returns logs."""
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
                 shards: int = 1, replicas: int = 0,
                 daily_index: bool = True) -> None:
        self.client = client
        self.log_index = log_index
        self.quarantine_index = quarantine_index
        self.shards = shards
        self.replicas = replicas
        self.daily_index = daily_index

    @property
    def read_index(self) -> str:
        # Include the legacy index for read-only transition. Never match quarantine.
        return f"{self.log_index},{self.log_index}-????.??.??" if self.daily_index else self.log_index

    def _daily_index(self, timestamp: str) -> str:
        try:
            stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("timestamp without timezone")
            day = stamp.astimezone(timezone.utc).strftime("%Y.%m.%d")
        except (TypeError, AttributeError, ValueError) as exc:
            raise StorageError("invalid timestamp for daily index") from exc
        return f"{self.log_index}-{day}"

    def _ensure_index(self, name: str, mapping: dict) -> None:
        try:
            if not self.client.indices.exists(index=name):
                self.client.indices.create(index=name, body={"settings": self._settings(),
                                                             "mappings": mapping})
        except Exception as exc:  # noqa: BLE001
            if "resource_already_exists_exception" not in str(exc):
                raise StorageError(f"cannot prepare index {name}: {exc}") from exc

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
            daily_index=config.LOG_INDEX_DAILY,
        )

    def _settings(self) -> dict:
        return {"index": {"number_of_shards": self.shards, "number_of_replicas": self.replicas}}

    def ensure_ready(self) -> None:
        # Create the current UTC day on startup; late-arriving days are created on write.
        today = self._daily_index(_iso_utc_now()) if self.daily_index else self.log_index
        self._ensure_index(today, LOG_MAPPING)
        self._ensure_index(self.quarantine_index, QUARANTINE_MAPPING)

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:  # noqa: BLE001
            return False

    # -- ghi
    def write_log(self, log_id: str, log: dict) -> None:
        target = self._daily_index(log["timestamp"]) if self.daily_index else self.log_index
        if self.daily_index:
            self._ensure_index(target, LOG_MAPPING)
        try:
            # same _id within same index => safe overwrite after keyed retry
            self.client.index(index=target, id=log_id, body=log)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"write_log failed: {exc}") from exc

    def write_logs(self, entries: list[tuple[str, dict]]) -> None:
        if not entries:
            return
        from opensearchpy.helpers import bulk

        targets = {self._daily_index(log["timestamp"]) if self.daily_index else self.log_index
                   for _, log in entries}
        for target in targets:
            self._ensure_index(target, LOG_MAPPING)
        actions = ({"_op_type": "index", "_index":
                    self._daily_index(log["timestamp"]) if self.daily_index else self.log_index,
                    "_id": log_id, "_source": log} for log_id, log in entries)
        try:
            # Helpers.bulk sends actual _bulk requests; unlike N per-document calls.
            success, errors = bulk(self.client, actions, raise_on_error=False,
                                   raise_on_exception=True, request_timeout=30)
            if errors or success != len(entries):
                raise StorageError(f"batch write incomplete ({success}/{len(entries)})")
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"batch write failed: {exc}") from exc

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
                     time_from: str | None, time_to: str | None,
                     level: str | None = None) -> dict:
        must: list[dict] = []
        filters: list[dict] = []
        if service:
            filters.append({"term": {"service": service}})
        if trace_id:
            filters.append({"term": {"trace_id": trace_id}})
        if level:
            filters.append({"term": {"level": level}})
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

    def _search_response(self, *, service: str | None = None, trace_id: str | None = None,
                         level: str | None = None, query: str | None = None,
                         time_from: str | None = None, time_to: str | None = None,
                         limit: int = 100, offset: int = 0,
                         with_facets: bool = False) -> tuple[list[dict], int, dict]:
        body = {
            "query": self._build_query(service, trace_id, query, time_from, time_to, level),
            "sort": [{"timestamp": {"order": "desc"}}],
            "from": offset,
            "size": limit,
            "track_total_hits": True,
        }
        if with_facets:
            body["aggs"] = {
                "timeline": {"date_histogram": {"field": "timestamp",
                                                "fixed_interval": "1h", "min_doc_count": 0}},
                "levels": {"terms": {"field": "level", "size": 5}},
                "services": {"terms": {"field": "service", "size": 20}},
            }
        try:
            resp = self.client.search(index=self.read_index, body=body,
                                      ignore_unavailable=True, allow_no_indices=True)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"search failed: {exc}") from exc
        total = resp["hits"]["total"]
        total = total["value"] if isinstance(total, dict) else int(total)
        aggs = resp.get("aggregations", {})
        facets = {name: aggs.get(name, {}).get("buckets", [])
                  for name in ("timeline", "levels", "services")}
        return [_with_log_id(h["_source"], h["_id"]) for h in resp["hits"]["hits"]], total, facets

    def search_with_total(self, **filters: Any) -> tuple[list[dict], int]:
        hits, total, _ = self._search_response(**filters)
        return hits, total

    def search_with_facets(self, **filters: Any) -> tuple[list[dict], int, dict]:
        return self._search_response(**filters, with_facets=True)

    def search(self, **filters: Any) -> list[dict]:
        return self.search_with_total(**filters)[0]

    def get_logs(self, log_ids: list[str]) -> list[dict]:
        if not log_ids:
            return []
        # A multi-index mget does not support wildcard _index; use ids query instead.
        found: dict[str, dict] = {}
        try:
            for offset in range(0, len(log_ids), 500):
                subset = log_ids[offset:offset + 500]
                resp = self.client.search(index=self.read_index, body={
                    "query": {"ids": {"values": subset}}, "size": len(subset)},
                    ignore_unavailable=True, allow_no_indices=True)
                for hit in resp["hits"]["hits"]:
                    found[hit["_id"]] = _with_log_id(hit["_source"], hit["_id"])
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"get_logs failed: {exc}") from exc
        return [found[i] for i in log_ids if i in found]

    def delete_older_than(self, cutoff_iso: str) -> int:
        if not self.daily_index:
            # Rollback-only compatibility for deployments that keep the legacy single index.
            try:
                response = self.client.delete_by_query(
                    index=self.log_index,
                    body={"query": {"range": {"timestamp": {"lt": cutoff_iso}}}},
                    conflicts="proceed", refresh=True, wait_for_completion=True,
                )
                return int(response.get("deleted", 0))
            except Exception as exc:  # noqa: BLE001
                raise StorageError(f"legacy retention failed: {exc}") from exc
        cutoff = datetime.fromisoformat(cutoff_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        try:
            names = self.client.indices.get(index=f"{self.log_index}-????.??.??",
                                            ignore_unavailable=True, allow_no_indices=True)
            deleted = 0
            for name in list(names):
                prefix = f"{self.log_index}-"
                if not name.startswith(prefix):
                    continue
                try:
                    day = datetime.strptime(name[len(prefix):], "%Y.%m.%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                # Drop only when the ENTIRE UTC day lies before cutoff.
                if day + timedelta(days=1) <= cutoff:
                    self.client.indices.delete(index=name)
                    deleted += 1
            return deleted
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"retention failed: {exc}") from exc


# --------------------------------------------------------------------------- In-memory (dev/test)

class InMemoryLogStore(LogStore):
    """Trien khai tam thoi (khong persist) de dev/test ma khong can OpenSearch that."""

    def __init__(self) -> None:
        self._logs: dict[str, dict] = {}
        self._quarantine: list[dict] = []

    def write_log(self, log_id: str, log: dict) -> None:
        self._logs[log_id] = log

    def write_logs(self, entries: list[tuple[str, dict]]) -> None:
        """Batch write; implementations may perform partial writes on backend failure."""
        for log_id, log in entries:
            self.write_log(log_id, log)

    def search_with_facets(self, **filters: Any) -> tuple[list[dict], int, dict]:
        results, total = self.search_with_total(**filters)
        return results, total, {"timeline": [], "levels": [], "services": []}

    def write_quarantine(self, log: dict, errors: list[str]) -> None:
        self._quarantine.append({"received_at": _iso_utc_now(), "log": log, "errors": errors})

    @staticmethod
    def _ts(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _matching(self, **filters: Any) -> list[dict]:
        results = [_with_log_id(log, log_id) for log_id, log in self._logs.items()]
        for field in ("service", "trace_id", "level"):
            if filters.get(field):
                results = [l for l in results if l.get(field) == filters[field]]
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
        return results

    def search_with_total(self, **filters: Any) -> tuple[list[dict], int]:
        results = self._matching(**filters)
        offset = filters.get("offset", 0)
        limit = filters.get("limit", 100)
        return results[offset:offset + limit], len(results)

    def search_with_facets(self, **filters: Any) -> tuple[list[dict], int, dict]:
        hits, total = self.search_with_total(**filters)
        all_hits = self._matching(**filters)
        hours: Counter[str] = Counter()
        for item in all_hits:
            hour = self._ts(item["timestamp"]).astimezone(timezone.utc).replace(
                minute=0, second=0, microsecond=0).isoformat()
            hours[hour] += 1
        def buckets(counter: Counter, limit: int) -> list[dict]:
            return [{"key": key, "doc_count": count} for key, count in counter.most_common(limit)]
        return hits, total, {
            "timeline": [{"key_as_string": key, "doc_count": hours[key]} for key in sorted(hours)],
            "levels": buckets(Counter(l["level"] for l in all_hits), 5),
            "services": buckets(Counter(l["service"] for l in all_hits), 20),
        }

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
