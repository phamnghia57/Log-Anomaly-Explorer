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

Cum bat thuong doc tu clustering.src.storage.OpenSearchStore (Nam) - cung
mot index `clusters` ma worker cua Nam ghi vao.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from ingestion.src import config
from ingestion.src.storage import LogStore, OpenSearchLogStore, StorageError, build_store

from .auth import require_admin, router as auth_router
from .telemetry import setup_telemetry
from .users import UserRepository

logger = logging.getLogger("query-api")

app = FastAPI(title="Log Anomaly Explorer - Query & Incident API")

# API doc log (GET) va login JSON (POST) - frontend deploy khac domain backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Pillar thu 3 cua observability (sau Logs o OpenSearch va Traces o Jaeger):
# METRICS. Expose /metrics dang Prometheus voi bo so RED (Rate/Errors/Duration)
# cho tung route: http_requests_total, http_request_duration_seconds.
# Nhan `handler` dung TEMPLATE route ("/clusters/{cluster_id}") chu khong phai
# duong dan that, nen khong no cardinality theo tung cluster_id.
#
# /metrics CO Y KHONG duoc route ra ngoai qua gateway (xem deploy/Caddyfile:
# chi mo /health, /search*, /clusters*, /docs) - so lieu van hanh chi nen doc
# tu trong mang noi bo, khong phoi ra Internet.
Instrumentator().instrument(app).expose(app, include_in_schema=False)

# Trace cho chinh query-api (khong chi demo-app) - xem src/telemetry.py.
setup_telemetry(app)

# Mot ket noi dung chung cho ca process, giong cach ingestion/src/main.py lam.
store: LogStore = build_store()
# Dung lai client hien co; memory backend chi ho tro cac route doc/dev, khong login.
app.state.user_repository = UserRepository(store) if isinstance(store, OpenSearchLogStore) else None
app.include_router(auth_router)


def _build_cluster_store():
    """ClusterStore cua Nam, hoac None khi chua dung duoc.

    OpenSearchStore yeu cau STORAGE_BACKEND=opensearch (xem
    clustering/src/storage.py), nen o che do dev `STORAGE_BACKEND=memory` no
    se khong tao duoc. Khi do tra None de /health va /search VAN chay binh
    thuong, chi rieng /clusters* bao 503 - thay vi lam sap ca service.
    """
    try:
        from clustering.src.storage import OpenSearchStore

        return OpenSearchStore()
    except Exception as exc:
        logger.warning("Chua doc duoc cum (%s: %s) - /clusters* se tra 503", type(exc).__name__, exc)
        return None


cluster_store = _build_cluster_store()

# api-contract.md: "from"/"to" mac dinh 24h gan nhat.
DEFAULT_WINDOW_HOURS = 24
# api-contract.md - GET /clusters: "since mac dinh theo retention hien hanh".
# Dung chung RETENTION_DAYS voi ingestion vi do la chinh sach dang ap dung cho
# log lam nen cho cum.
DEFAULT_CLUSTER_WINDOW_DAYS = config.RETENTION_DAYS


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


@app.get("/search", dependencies=[Depends(require_admin)])
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


def _require_cluster_store():
    if cluster_store is None:
        raise HTTPException(
            status_code=503,
            detail="cluster store chua san sang (can STORAGE_BACKEND=opensearch va OpenSearch dang chay)",
        )
    return cluster_store


@app.get("/clusters", dependencies=[Depends(require_admin)])
def list_clusters(
    status: str | None = None,
    since: str | None = None,
    limit: int = Query(default=config.DEFAULT_SEARCH_LIMIT, ge=1, le=config.MAX_SEARCH_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Danh sach cum bat thuong, doc tu ClusterRecord that cua Nam.

    Khong truyen `since` thi mac dinh lay theo retention hien hanh
    (RETENTION_DAYS), dung theo api-contract.md.
    """
    clusters = _require_cluster_store()
    start = _parse_dt(since, "since")
    if start is None:
        start = (datetime.now(timezone.utc) - timedelta(days=DEFAULT_CLUSTER_WINDOW_DAYS)).isoformat()

    try:
        results = clusters.list_clusters(status=status, since=start, limit=limit, offset=offset)
    except ValueError as exc:  # status khong hop le -> loi cua nguoi goi, khong phai 500
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"total": len(results), "clusters": results}


@app.get("/clusters/{cluster_id}", dependencies=[Depends(require_admin)])
def get_cluster(
    cluster_id: str,
    logs_limit: int = Query(default=config.DEFAULT_SEARCH_LIMIT, ge=1, le=config.MAX_SEARCH_LIMIT),
    logs_offset: int = Query(default=0, ge=0),
):
    """Incident View: chi tiet cum + log goc da gay ra no.

    `logs` duoc dien bang cach tra `log_ids` cua ClusterRecord ve LogStore -
    moi log kem `log_id` (xem ingestion/src/storage.py::_with_log_id) de doi
    chieu duoc voi `log_ids`.

    `logs` duoc PHAN TRANG (`logs_limit`/`logs_offset`): mot cum co the gom
    hang tram log, tra het trong mot response lam endpoint nay cham nhat toan
    he thong (do duoc: median 530ms, p99 1.7s - xem load-tests/README.md).
    `logs_total` la tong so log_ids cua cum, khong bi cat boi `logs_limit`,
    de UI biet con bao nhieu log chua tai.
    """
    clusters = _require_cluster_store()
    cluster = clusters.get_cluster(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="cluster not found")

    log_ids = cluster.get("log_ids", [])
    logs = store.get_logs(log_ids[logs_offset:logs_offset + logs_limit])
    return {**cluster, "logs": logs, "logs_total": len(log_ids)}


@app.get("/clusters/{cluster_id}/history", dependencies=[Depends(require_admin)])
def get_cluster_history(
    cluster_id: str,
    since: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Xu huong anomaly score theo thoi gian cua MOT cum (bieu do), khac
    GET /clusters/{cluster_id} (chi 1 diem hien tai).

    Doc tu index `cluster-history` qua clusters.list_history() (Nghia chuan
    bi truoc) - xem docs/architect/contracts/cluster-history-schema.json.
    `points` rong la hop le: cum ton tai nhung Nam chua trien khai phan ghi.
    """
    clusters = _require_cluster_store()
    if clusters.get_cluster(cluster_id) is None:
        raise HTTPException(status_code=404, detail="cluster not found")

    start = _parse_dt(since, "since")
    if start is None:
        start = (datetime.now(timezone.utc) - timedelta(days=DEFAULT_CLUSTER_WINDOW_DAYS)).isoformat()

    try:
        points = clusters.list_history(cluster_id, since=start, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"cluster_id": cluster_id, "points": points}
