"""Test cho query-api: /health va /search (da noi vao LogStore that cua Minh).

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

    def test_log_tra_ve_HIEN_CHUA_CO_log_id(self):
        """GAP DA PHAT HIEN (2026-10-22, qua chinh test nay): LogStore cua
        Minh khong gan `log_id` vao document (OpenSearch de id o `_id`,
        in-memory luu nguyen dict), nen log tra ve khong co truong nay.

        Hau qua: Incident View (/clusters/{id}) se khong doi chieu duoc
        `log_ids` cua ClusterRecord sang log cu the. Nam da phai tu va trong
        code cua minh ({**hit["_source"], "log_id": hit["_id"]}) - dau hieu
        cho thay cho sua dung la o LogStore, khong phai moi nguoi tu va.

        Test nay ghi lai HANH VI HIEN TAI (khong phai hanh vi mong muon). Khi
        Minh sua, test se do -> cap nhat lai, khong de lang le bo sot.
        """
        write("1")
        results = client.get("/search").json()["results"]
        assert "log_id" not in results[0]

    def test_limit_vuot_nguong_cho_phep_tra_422(self):
        resp = client.get("/search", params={"limit": 10_000})
        assert resp.status_code == 422

    def test_storage_loi_tra_503(self, monkeypatch):
        def boom(**_kwargs):
            raise StorageError_("mat ket noi")

        from ingestion.src.storage import StorageError as StorageError_

        monkeypatch.setattr(main.store, "search_with_total", boom)
        assert client.get("/search").status_code == 503
