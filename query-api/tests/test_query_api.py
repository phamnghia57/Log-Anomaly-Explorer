"""Test cho query-api: /health, /search (LogStore cua Minh) va /clusters*
(ClusterStore cua Nam).

Dung STORAGE_BACKEND=memory (xem conftest.py) nen khong can OpenSearch.
Import bang importlib vi ten thu muc "query-api" co dau "-", khong dung duoc
cu phap `import query-api.src.main`.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

main = importlib.import_module("query-api.src.main")
client = TestClient(main.app)


def iso(hours_ago: float = 0) -> str:
    """Thoi diem TUONG DOI: /search mac dinh chi lay 24h gan nhat, nen moc
    thoi gian co dinh se tu roi ra ngoai cua so khi thoi gian troi qua."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture(autouse=True)
def _reset_store():
    """store la bien module dung chung ca process -> don giua cac test."""
    main.store._logs.clear()
    yield


def write(log_id: str, **over) -> None:
    log = {"timestamp": iso(), "level": "ERROR", "service": "demo-web",
           "trace_id": "t1", "span_id": "s1", "message": "Simulated failure in checkout"}
    log.update(over)
    main.store.write_log(log_id, log)


class TestHealth:
    def test_health_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "query-api"


class TestSearch:
    def test_khong_filter_tra_ve_tat_ca(self):
        write("1")
        write("2")
        body = client.get("/search").json()
        assert body["total"] == 2
        assert len(body["results"]) == 2

    def test_filter_theo_service(self):
        write("1", service="demo-web")
        write("2", service="demo-mobile-api")
        body = client.get("/search", params={"service": "demo-mobile-api"}).json()
        assert body["total"] == 1

    def test_filter_theo_trace_id(self):
        write("1", trace_id="a")
        write("2", trace_id="b")
        body = client.get("/search", params={"trace_id": "a"}).json()
        assert body["total"] == 1

    def test_filter_full_text_tren_message(self):
        write("1", message="db timeout khi goi payment")
        write("2", message="moi thu binh thuong")
        body = client.get("/search", params={"q": "timeout"}).json()
        assert body["total"] == 1

    def test_mac_dinh_chi_lay_24h_gan_nhat(self):
        write("cu", timestamp=iso(hours_ago=72))
        write("moi")
        body = client.get("/search").json()
        assert body["total"] == 1
        assert body["results"][0]["timestamp"] == main.store._logs["moi"]["timestamp"]

    def test_from_to_dung_alias_dung_theo_api_contract(self):
        """api-contract.md dat ten tham so la `from`/`to` - khong phai
        time_from/time_to (`from` la tu khoa Python nen phai dung alias)."""
        write("cu", timestamp=iso(hours_ago=72))
        write("moi")
        body = client.get("/search", params={"from": iso(hours_ago=100), "to": iso(hours_ago=-1)}).json()
        assert body["total"] == 2

    def test_timestamp_sai_dinh_dang_tra_400(self):
        resp = client.get("/search", params={"from": "hom qua"})
        assert resp.status_code == 400

    def test_total_khong_bi_cat_boi_limit(self):
        for i in range(5):
            write(f"t{i}")
        body = client.get("/search", params={"limit": 2}).json()
        assert body["total"] == 5          # tong so khop
        assert len(body["results"]) == 2   # so ban ghi tra ve trang nay

    def test_offset_phan_trang(self):
        for i in range(5):
            write(f"t{i}", trace_id=f"trace-{i}")
        trang1 = client.get("/search", params={"limit": 2, "offset": 0}).json()["results"]
        trang2 = client.get("/search", params={"limit": 2, "offset": 2}).json()["results"]
        assert {l["trace_id"] for l in trang1}.isdisjoint({l["trace_id"] for l in trang2})

    def test_log_tra_ve_co_log_id(self):
        """LogStore gan `log_id` luc DOC (khong luu luc ghi), nen Incident View
        doi chieu duoc `log_ids` cua ClusterRecord sang log cu the."""
        write("1")
        results = client.get("/search").json()["results"]
        assert results[0]["log_id"] == "1"

    def test_limit_vuot_nguong_cho_phep_tra_422(self):
        resp = client.get("/search", params={"limit": 10_000})
        assert resp.status_code == 422

    def test_storage_loi_tra_503(self, monkeypatch):
        def boom(**_kwargs):
            raise StorageError_("mat ket noi")

        from ingestion.src.storage import StorageError as StorageError_

        monkeypatch.setattr(main.store, "search_with_total", boom)
        assert client.get("/search").status_code == 503


class FakeClusterStore:
    """Thay OpenSearchStore that cua Nam trong test - giu dung chu ky da cong bo
    trong clustering/src/storage.py (list_clusters/get_cluster)."""

    def __init__(self, records=None):
        self.records = list(records or [])
        self.calls = []
        self.history_points: dict[str, list[dict]] = {}

    def list_clusters(self, *, status=None, since=None, limit=100, offset=0):
        self.calls.append({"status": status, "since": since, "limit": limit, "offset": offset})
        if status is not None and status not in {"normal", "anomalous", "alerted"}:
            raise ValueError("Invalid cluster status")
        results = [r for r in self.records if status is None or r["status"] == status]
        return results[offset:offset + limit]

    def get_cluster(self, cluster_id):
        self.calls.append({"get": cluster_id})
        return next((r for r in self.records if r["cluster_id"] == cluster_id), None)

    def list_history(self, cluster_id, *, since=None, limit=100):
        self.calls.append({"history": cluster_id, "since": since, "limit": limit})
        if limit < 1:
            raise ValueError("limit must be positive")
        return list(self.history_points.get(cluster_id, []))


def test_fake_khop_chu_ky_that_cua_clustering():
    """FakeClusterStore phai khop chu ky that cua clustering/src/storage.py.

    Neu Nam doi chu ky (doi ten tham so, bo tham so...) ma fake khong doi theo,
    cac test duoi se van xanh trong khi chay that thi vo - test nay bat duoc
    dieu do ngay.
    """
    import inspect

    from clustering.src.storage import OpenSearchStore

    for name in ("list_clusters", "get_cluster", "list_history"):
        that = inspect.signature(getattr(OpenSearchStore, name))
        gia = inspect.signature(getattr(FakeClusterStore, name))
        assert that == gia, f"{name}: that={that} khac fake={gia}"


def record(cluster_id="c1", status="alerted", **over) -> dict:
    base = {"cluster_id": cluster_id, "signature": "simulated failure in checkout",
            "score": 3.2, "log_ids": [], "trace_ids": ["t1"],
            "first_seen": iso(hours_ago=1), "last_seen": iso(), "status": status}
    base.update(over)
    return base


@pytest.fixture
def clusters(monkeypatch):
    """cluster_store la bien module (co the la None khi chay memory backend),
    nen test gan thang vao module - giong cach main.store duoc thay o tren."""
    fake = FakeClusterStore()
    monkeypatch.setattr(main, "cluster_store", fake)
    return fake


class TestListClusters:
    def test_tra_ve_cum_tu_cluster_store(self, clusters):
        clusters.records = [record("c1"), record("c2", status="normal")]
        body = client.get("/clusters").json()
        assert body["total"] == 2
        assert {c["cluster_id"] for c in body["clusters"]} == {"c1", "c2"}

    def test_loc_theo_status(self, clusters):
        clusters.records = [record("c1", status="alerted"), record("c2", status="normal")]
        body = client.get("/clusters", params={"status": "alerted"}).json()
        assert [c["cluster_id"] for c in body["clusters"]] == ["c1"]

    def test_status_khong_hop_le_tra_400(self, clusters):
        resp = client.get("/clusters", params={"status": "khong-ton-tai"})
        assert resp.status_code == 400

    def test_khong_truyen_since_thi_mac_dinh_theo_retention(self, clusters):
        client.get("/clusters")
        since = clusters.calls[-1]["since"]
        assert since is not None
        nguong = datetime.now(timezone.utc) - timedelta(days=main.DEFAULT_CLUSTER_WINDOW_DAYS)
        assert abs((datetime.fromisoformat(since) - nguong).total_seconds()) < 60

    def test_since_sai_dinh_dang_tra_400(self, clusters):
        assert client.get("/clusters", params={"since": "hom qua"}).status_code == 400

    def test_cluster_store_chua_san_sang_tra_503(self, monkeypatch):
        """Chay voi STORAGE_BACKEND=memory thi khong tao duoc OpenSearchStore -
        /clusters* phai bao 503 ro rang, khong duoc lam sap ca service."""
        monkeypatch.setattr(main, "cluster_store", None)
        assert client.get("/clusters").status_code == 503
        assert client.get("/health").status_code == 200  # /health van song
        assert client.get("/search").status_code == 200  # /search van song


class TestGetCluster:
    def test_khong_ton_tai_tra_404(self, clusters):
        assert client.get("/clusters/khong-co").status_code == 404

    def test_dien_day_du_logs_tu_log_ids(self, clusters):
        """Day la Incident View: tra `log_ids` cua ClusterRecord ve LogStore."""
        write("log-1")
        write("log-2")
        write("log-khac")
        clusters.records = [record("c1", log_ids=["log-1", "log-2"])]

        body = client.get("/clusters/c1").json()
        assert body["cluster_id"] == "c1"
        assert {l["log_id"] for l in body["logs"]} == {"log-1", "log-2"}

    def test_log_ids_rong_tra_logs_rong(self, clusters):
        clusters.records = [record("c1", log_ids=[])]
        assert client.get("/clusters/c1").json()["logs"] == []

    def test_log_id_khong_con_ton_tai_thi_bo_qua(self, clusters):
        """Log het han retention bi xoa -> cum van xem duoc, chi thieu log do."""
        write("log-1")
        clusters.records = [record("c1", log_ids=["log-1", "da-bi-xoa"])]
        body = client.get("/clusters/c1").json()
        assert [l["log_id"] for l in body["logs"]] == ["log-1"]
        # logs_total dem theo log_ids cua cum, khong theo so log con doc duoc
        assert body["logs_total"] == 2


class TestGetClusterLogsPagination:
    """`logs` trong Incident View duoc phan trang - cum hang tram log khong
    con tra het trong mot response (xem load-tests/README.md)."""

    def _cum_nhieu_log(self, clusters, total=250):
        ids = []
        for i in range(total):
            write(f"log-{i:03d}")
            ids.append(f"log-{i:03d}")
        clusters.records = [record("c1", log_ids=ids)]
        return ids

    def test_mac_dinh_chi_tra_mot_trang(self, clusters):
        self._cum_nhieu_log(clusters, total=250)
        body = client.get("/clusters/c1").json()
        assert len(body["logs"]) == main.config.DEFAULT_SEARCH_LIMIT
        assert body["logs_total"] == 250  # tong khong bi cat boi limit

    def test_offset_lay_trang_tiep_theo_khong_trung_lap(self, clusters):
        self._cum_nhieu_log(clusters, total=250)
        trang1 = client.get("/clusters/c1", params={"logs_limit": 10, "logs_offset": 0}).json()
        trang2 = client.get("/clusters/c1", params={"logs_limit": 10, "logs_offset": 10}).json()

        ids1 = {l["log_id"] for l in trang1["logs"]}
        ids2 = {l["log_id"] for l in trang2["logs"]}
        assert len(ids1) == len(ids2) == 10
        assert ids1.isdisjoint(ids2)

    def test_offset_vuot_qua_tong_tra_logs_rong(self, clusters):
        self._cum_nhieu_log(clusters, total=5)
        body = client.get("/clusters/c1", params={"logs_offset": 999}).json()
        assert body["logs"] == []
        assert body["logs_total"] == 5

    def test_logs_limit_vuot_nguong_cho_phep_tra_422(self, clusters):
        clusters.records = [record("c1")]
        assert client.get("/clusters/c1", params={"logs_limit": 10_000}).status_code == 422


class TestMetrics:
    """Pillar thu 3 cua observability: Metrics dang Prometheus (xem src/main.py)."""

    def test_tra_ve_dinh_dang_prometheus_voi_bo_so_red(self):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "http_requests_total" in resp.text             # Rate + Errors (co nhan status)
        assert "http_request_duration_seconds" in resp.text   # Duration

    def test_nhan_handler_la_template_route_khong_phai_duong_dan_that(self, clusters):
        """Neu nhan `handler` dung duong dan that thi moi cluster_id lai tao mot
        time series rieng -> no cardinality, Prometheus phinh bo nho."""
        clusters.records = [record("c1")]
        client.get("/clusters/c1")

        text = client.get("/metrics").text
        assert 'handler="/clusters/{cluster_id}"' in text
        assert "/clusters/c1" not in text


class TestClusterHistory:
    """GET /clusters/{id}/history - xu huong score theo thoi gian (cluster-history-schema.json)."""

    def test_tra_ve_cac_diem_cua_dung_cum(self, clusters):
        clusters.records = [record("c1")]
        clusters.history_points["c1"] = [
            {"cluster_id": "c1", "score": 1.0, "status": "normal", "recorded_at": iso(hours_ago=2)},
            {"cluster_id": "c1", "score": 5.0, "status": "anomalous", "recorded_at": iso(hours_ago=1)},
        ]

        body = client.get("/clusters/c1/history").json()
        assert body["cluster_id"] == "c1"
        assert [p["score"] for p in body["points"]] == [1.0, 5.0]

    def test_cum_khong_ton_tai_tra_404(self, clusters):
        assert client.get("/clusters/khong-co/history").status_code == 404

    def test_chua_co_history_tra_points_rong(self, clusters):
        """cum ton tai nhung Nam chua ghi history - points rong la hop le, khong phai loi."""
        clusters.records = [record("c1")]
        body = client.get("/clusters/c1/history").json()
        assert body["points"] == []

    def test_khong_truyen_since_thi_mac_dinh_theo_retention(self, clusters):
        clusters.records = [record("c1")]
        client.get("/clusters/c1/history")
        since = next(c for c in clusters.calls if "history" in c)["since"]
        nguong = datetime.now(timezone.utc) - timedelta(days=main.DEFAULT_CLUSTER_WINDOW_DAYS)
        assert abs((datetime.fromisoformat(since) - nguong).total_seconds()) < 60

    def test_since_sai_dinh_dang_tra_400(self, clusters):
        clusters.records = [record("c1")]
        resp = client.get("/clusters/c1/history", params={"since": "hom qua"})
        assert resp.status_code == 400

    def test_limit_vuot_nguong_cho_phep_tra_422(self, clusters):
        clusters.records = [record("c1")]
        resp = client.get("/clusters/c1/history", params={"limit": 10_000})
        assert resp.status_code == 422

    def test_cluster_store_chua_san_sang_tra_503(self, monkeypatch):
        monkeypatch.setattr(main, "cluster_store", None)
        assert client.get("/clusters/c1/history").status_code == 503
