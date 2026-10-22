"""
Query & Incident API - Nghia.

Search log + Incident View (chi tiet cum + lien ket trace/request).
Xem docs/architect/contracts/api-contract.md muc "Query & Incident API".

Dung chung MOT kho du lieu voi Ingestion bang cach import thang
`ingestion.src.storage` (khong goi HTTP sang ingestion) - cung cach
clustering doc log. Vi vay PHAI chay tu THU MUC GOC repo de Python tim
duoc package `ingestion`:

    pip install -r query-api/requirements.txt
    uvicorn query-api.src.main:app --reload --port 8002

Khong co OpenSearch? Dung backend nhe (phai khop voi backend ingestion dang
ghi vao, neu khong se doc mot kho rong khac):

    STORAGE_BACKEND=memory uvicorn query-api.src.main:app --reload --port 8002

Trang thai: /health va /search da noi vao du lieu THAT. /clusters va
/clusters/{id} van la mock - cho Nam hoan thien phan doc ClusterRecord
(`list_clusters`/`get_cluster`) trong clustering/src/storage.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from ingestion.src import config
from ingestion.src.storage import LogStore, StorageError, build_store

app = FastAPI(title="Log Anomaly Explorer - Query & Incident API")

# Mot ket noi dung chung cho ca process, giong cach ingestion/src/main.py lam.
store: LogStore = build_store()

# api-contract.md: "from"/"to" mac dinh 24h gan nhat.
DEFAULT_WINDOW_HOURS = 24


@app.exception_handler(StorageError)
async def _storage_error(_, exc: StorageError):
    return JSONResponse(status_code=503, content={"error": "storage_unavailable", "detail": str(exc)})


def _parse_dt(value: str | None, name: str) -> str | None:
    """Chuan hoa ISO 8601 ve UTC. Sai dinh dang -> 400 (khong de lot xuong
    tang storage roi bao loi kho hieu).

    Tu parse thay vi dung lai ham rieng trong ingestion/src/main.py: query-api
    chi nen phu thuoc vao INTERFACE storage da cong bo (LogStore), khong phu
    thuoc chi tiet noi bo tang HTTP cua service khac.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} phai la ISO 8601 date-time") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


@app.get("/health")
def health():
    ok = store.ping()
    body = {"status": "ok" if ok else "degraded", "service": "query-api",
            "storage": config.STORAGE_BACKEND}
    return JSONResponse(status_code=200 if ok else 503, content=body)


@app.get("/search")
def search(
    service: str | None = None,
    trace_id: str | None = None,
    q: str | None = None,
    time_from: str | None = Query(default=None, alias="from"),
    time_to: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=config.DEFAULT_SEARCH_LIMIT, ge=1, le=config.MAX_SEARCH_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Tim log tho theo field (khong phai semantic/vector search).

    Khong truyen ca `from` lan `to` thi mac dinh lay 24h gan nhat.
    `total` la tong so ban ghi khop, khong bi cat boi `limit` (de UI phan trang).
    """
    start = _parse_dt(time_from, "from")
    end = _parse_dt(time_to, "to")
    if start is None and end is None:
        start = (datetime.now(timezone.utc) - timedelta(hours=DEFAULT_WINDOW_HOURS)).isoformat()

    results, total = store.search_with_total(
        service=service, trace_id=trace_id, query=q,
        time_from=start, time_to=end, limit=limit, offset=offset,
    )
    return {"total": total, "results": results}


# TODO (Nghia): 2 endpoint duoi van la mock - chua noi duoc vi
# clustering/src/storage.py (Nam) hien moi co write_cluster, chua co ham doc
# (list_clusters/get_cluster). Noi vao ngay khi PR cua Nam merge.
_MOCK_CLUSTERS: dict[str, dict] = {
    "example-cluster-1": {
        "cluster_id": "example-cluster-1",
        "score": 3.2,
        "status": "alerted",
        "logs": [],
        "trace_ids": ["abc123"],
    }
}


@app.get("/clusters")
def list_clusters(status: str | None = None):
    results = list(_MOCK_CLUSTERS.values())
    if status:
        results = [c for c in results if c["status"] == status]
    return {"total": len(results), "clusters": results}


@app.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: str):
    cluster = _MOCK_CLUSTERS.get(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="cluster not found")
    # TODO (Nghia): dien day du "logs" bang store.get_logs(cluster["log_ids"]) -
    # day chinh la Incident View. Cho ClusterRecord that cua Nam.
    return cluster
