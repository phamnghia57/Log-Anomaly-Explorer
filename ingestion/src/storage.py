"""
Storage client cho log da chuan hoa.

TODO (Minh): chon MOT trong hai va cai dat that:
  - Elasticsearch / OpenSearch: phu hop Search (MVP) - tim kiem full-text, loc nhieu truong.
  - ClickHouse: phu hop tinh toan tan suat cho Anomaly Score (MVP) nhanh hon o quy mo lon.

Giu interface duoi day on dinh de clustering (Nam) va query-api
(Nghia) khong bi anh huong khi doi engine luu tru.
"""

from __future__ import annotations

from typing import Any


class LogStore:
    """Interface luu & truy van log. Cai dat cu the trong lop con."""

    def write_log(self, log_id: str, log: dict) -> None:
        raise NotImplementedError

    def write_quarantine(self, log: dict, errors: list[str]) -> None:
        """Log sai schema - luu rieng, KHONG vao index chinh (xem docs/contracts/api-contract.md)."""
        raise NotImplementedError

    def search(self, *, service: str | None = None, trace_id: str | None = None,
               query: str | None = None, time_from: str | None = None,
               time_to: str | None = None) -> list[dict]:
        """Dung boi Nghia (GET /search)."""
        raise NotImplementedError

    def delete_older_than(self, cutoff_iso: str) -> int:
        """Dung boi retention job (xem retention.py). Tra ve so log da xoa."""
        raise NotImplementedError


class InMemoryLogStore(LogStore):
    """Trien khai tam thoi (khong persist) de cac module khac dev/test ma khong can
    dung ES/OpenSearch/ClickHouse that. THAY THE bang LogStore that truoc khi bàn giao.
    """

    def __init__(self) -> None:
        self._logs: dict[str, dict] = {}
        self._quarantine: list[dict] = []

    def write_log(self, log_id: str, log: dict) -> None:
        self._logs[log_id] = log

    def write_quarantine(self, log: dict, errors: list[str]) -> None:
        self._quarantine.append({"log": log, "errors": errors})

    def search(self, **filters: Any) -> list[dict]:
        results = list(self._logs.values())
        if filters.get("service"):
            results = [l for l in results if l.get("service") == filters["service"]]
        if filters.get("trace_id"):
            results = [l for l in results if l.get("trace_id") == filters["trace_id"]]
        if filters.get("query"):
            q = filters["query"].lower()
            results = [l for l in results if q in l.get("message", "").lower()]
        return results

    def delete_older_than(self, cutoff_iso: str) -> int:
        before = len(self._logs)
        self._logs = {k: v for k, v in self._logs.items() if v["timestamp"] >= cutoff_iso}
        return before - len(self._logs)
