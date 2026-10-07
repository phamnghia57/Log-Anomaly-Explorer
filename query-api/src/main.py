"""
Query & Incident API - Nghia.

Search log + Incident View (chi tiet cum + lien ket trace/request).
Dung chung storage cua Ingestion (Minh) va cluster data cua
Clustering (Nam) - xem docs/architect/contracts/api-contract.md.

Chay thu (voi du lieu gia tam thoi, chua noi that voi Minh/Nam):
    pip install -r query-api/requirements.txt
    uvicorn query-api.src.main:app --reload --port 8002
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Log Anomaly Explorer - Query & Incident API")

# TODO (Nghia): thay bang client that goi sang ingestion.src.storage.LogStore
# va noi voi noi Nam ghi ClusterRecord.
_MOCK_CLUSTERS: dict[str, dict] = {
    "example-cluster-1": {
        "cluster_id": "example-cluster-1",
        "score": 3.2,
        "status": "alerted",
        "logs": [],
        "trace_ids": ["abc123"],
    }
}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "query-api"}


@app.get("/search")
def search(
    service: str | None = None,
    trace_id: str | None = None,
    q: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
):
    """TODO: goi sang ingestion storage that. Hien tra ve placeholder."""
    raise NotImplementedError("Nghia: noi sang LogStore that cua Minh")


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
    # TODO (Nghia): dien day du "logs" bang cach tra cuu log_ids
    # tu LogStore that, dung cho Incident View.
    return cluster
