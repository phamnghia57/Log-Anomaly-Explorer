"""Tool (function-calling) ma AI Assistant co the tu goi de dieu tra them -
giong cac function `elasticsearch`/`query`/`alerts` cua Elastic Observability
AI Assistant, nhung goi THANG vao du lieu that cua he thong nay (LogStore,
ClusterStore da co san) thay vi chay truy van tuy y - khong can them quyen
truy cap OpenSearch moi.

Chi doc (read-only). Khong co tool ghi/sua du lieu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Mac dinh tim trong 24h gan nhat neu AI khong chi dinh - giong default cua
# GET /search (api-contract.md), tranh quet toan bo lich su khi AI chi can
# ngu canh gan day.
DEFAULT_SEARCH_WINDOW_HOURS = 24

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

_CLUSTER_SUMMARY_FIELDS = ("cluster_id", "signature", "score", "status", "last_seen")


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
        return {"total": total, "results": results}

    def _tool_list_active_clusters(self, arguments: dict) -> dict:
        if self.cluster_store is None:
            return {"error": "cluster store unavailable"}
        limit = min(int(arguments.get("limit") or 10), 20)
        clusters = self.cluster_store.list_clusters(status=arguments.get("status"), limit=limit)
        return {"clusters": [
            {field: c[field] for field in _CLUSTER_SUMMARY_FIELDS if field in c} for c in clusters
        ]}
