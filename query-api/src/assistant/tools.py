"""Tool (function-calling) ma AI Assistant co the tu goi de dieu tra them -
giong cac function `elasticsearch`/`query`/`alerts` cua Elastic Observability
AI Assistant, nhung goi THANG vao du lieu that cua he thong nay (LogStore,
ClusterStore da co san) thay vi chay truy van tuy y - khong can them quyen
truy cap OpenSearch moi.

Chi doc (read-only). Khong co tool ghi/sua du lieu.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx

from . import config

# Mac dinh tim trong 24h gan nhat neu AI khong chi dinh - giong default cua
# GET /search (api-contract.md), tranh quet toan bo lich su khi AI chi can
# ngu canh gan day.
DEFAULT_SEARCH_WINDOW_HOURS = 24
# Stack trace that co the dai hang nghin ky tu; cat bot truoc khi dua vao prompt
# (system prompt va ket qua tool) - phan dau da du de nhan ra nguyen nhan, giu
# nguyen ca cai chi lam phinh token va cham vong goi model tiep theo.
MAX_STACK_TRACE_CHARS = 500
MAX_TRACE_SPANS = 50
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{1,32}$")
TRACE_NOT_FOUND_HINT = ("Jaeger giu trace trong RAM nen trace cu hoac trace truoc lan restart "
                        "gan nhat co the da bi day ra; khong ket luan la request khong xay ra.")

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_cluster_history",
            "description": "Lay xu huong anomaly score theo thoi gian cua CHINH cum dang dieu tra (toi da 50 diem gan nhat).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_related_logs",
            "description": (
                "Tim log tho theo service/tu khoa trong 24h gan nhat - dung de kiem tra cac log "
                "hoac loi KHAC co lien quan nhung khong thuoc cum dang dieu tra (vd. loi tren "
                "service khac xay ra cung thoi diem)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Loc theo service, vi du demo-web"},
                    "q": {"type": "string", "description": "Tu khoa tim trong message"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_clusters",
            "description": (
                "Liet ke cac cum bat thuong/da alert KHAC dang xay ra gan day - dung de kiem tra "
                "su co dang dieu tra co lan sang service khac cung luc khong."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["anomalous", "alerted"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
        },
    },
]

_GET_TRACE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_trace",
        "description": (
            "Doc trace phan tan theo trace_id lay tu log - tra ve danh sach span theo thu tu "
            "thoi gian kem service, operation, thoi gian chay (ms) va co loi hay khong. Dung "
            "de biet CHINH XAC buoc nao trong request bi cham hoac that bai, thay vi chi doan "
            "tu message cua log."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "trace_id hex lay tu log mau hoac search_related_logs"},
            },
            "required": ["trace_id"],
            "additionalProperties": False,
        },
    },
}


def tool_schemas() -> list[dict]:
    if not config.JAEGER_QUERY_URL:
        return list(TOOL_SCHEMAS)
    return [*TOOL_SCHEMAS, _GET_TRACE_SCHEMA]


_CLUSTER_SUMMARY_FIELDS = ("cluster_id", "signature", "score", "status", "last_seen")
_LOG_SUMMARY_FIELDS = ("timestamp", "service", "level", "message", "trace_id")


def _span_summary(span: dict, processes: dict) -> dict:
    tags = {tag.get("key"): tag.get("value") for tag in span.get("tags") or []}
    summary = {
        "service": (processes.get(span.get("processID")) or {}).get("serviceName"),
        "operation": span.get("operationName"),
        "duration_ms": round((span.get("duration") or 0) / 1000, 1),
    }
    if tags.get("error") is True or str(tags.get("otel.status_code", "")).upper() == "ERROR":
        summary["error"] = True
    if "http.status_code" in tags:
        summary["http_status"] = tags["http.status_code"]
    return summary


def _log_summary(log: dict) -> dict:
    summary = {field: log[field] for field in _LOG_SUMMARY_FIELDS if field in log}
    if log.get("stack_trace"):
        summary["stack_trace"] = log["stack_trace"][:MAX_STACK_TRACE_CHARS]
    return summary


class ToolExecutor:
    """Thuc thi 1 tool call theo ten - tra ve dict (se duoc json.dumps lai
    thanh noi dung message role=tool). Loi tool khong duoc van vo ca luot
    chat - tra ve {"error": ...} de AI tu doc va quyet dinh buoc tiep theo.
    """

    def __init__(self, *, store, cluster_store, cluster_id: str):
        self.store = store
        self.cluster_store = cluster_store
        self.cluster_id = cluster_id

    def run(self, name: str, arguments: dict) -> dict:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return handler(arguments)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _tool_get_cluster_history(self, _arguments: dict) -> dict:
        if self.cluster_store is None:
            return {"error": "cluster store unavailable"}
        points = self.cluster_store.list_history(self.cluster_id, limit=50)
        return {"points": points}

    def _tool_search_related_logs(self, arguments: dict) -> dict:
        limit = min(int(arguments.get("limit") or 10), 50)
        time_from = (datetime.now(timezone.utc) - timedelta(hours=DEFAULT_SEARCH_WINDOW_HOURS)).isoformat()
        results, total = self.store.search_with_total(
            service=arguments.get("service"), query=arguments.get("q"),
            time_from=time_from, limit=limit,
        )
        # Chi giu field AI thuc su dung: nhoi nguyen log document (ca metadata,
        # stack_trace day) vao message role=tool lam phinh token vong goi tiep theo.
        return {"total": total, "results": [_log_summary(log) for log in results]}

    def _tool_get_trace(self, arguments: dict) -> dict:
        if not config.JAEGER_QUERY_URL:
            return {"error": "jaeger is not configured"}
        trace_id = str(arguments.get("trace_id") or "").strip()
        if not _TRACE_ID_PATTERN.match(trace_id):
            return {"error": "trace_id must be a hex string of at most 32 characters"}
        response = httpx.get(f"{config.JAEGER_QUERY_URL}/api/traces/{trace_id}",
                             timeout=config.JAEGER_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return {"error": "trace not found", "hint": TRACE_NOT_FOUND_HINT}
        response.raise_for_status()
        traces = response.json().get("data") or []
        if not traces:
            return {"error": "trace not found", "hint": TRACE_NOT_FOUND_HINT}
        processes = traces[0].get("processes") or {}
        spans = sorted(traces[0].get("spans") or [], key=lambda span: span.get("startTime") or 0)
        return {
            "trace_id": traces[0].get("traceID") or trace_id,
            "span_count": len(spans),
            "spans": [_span_summary(span, processes) for span in spans[:MAX_TRACE_SPANS]],
        }

    def _tool_list_active_clusters(self, arguments: dict) -> dict:
        if self.cluster_store is None:
            return {"error": "cluster store unavailable"}
        limit = min(int(arguments.get("limit") or 10), 20)
        clusters = self.cluster_store.list_clusters(status=arguments.get("status"), limit=limit)
        return {"clusters": [
            {field: c[field] for field in _CLUSTER_SUMMARY_FIELDS if field in c} for c in clusters
        ]}
