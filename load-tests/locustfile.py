"""
Load test cho Log Anomaly Explorer, dung Locust.

Hai nhom nguoi dung mo phong 2 phia cua he thong:

    IngestionUser  - tang ingestion (Minh): lien tuc gui log ve POST /ingest.
    QueryUser      - end-to-end (Nghia): doc qua Query & Incident API, bao gom
                     ca luong Incident View that (liet ke cum -> mo chi tiet
                     mot cum -> keo log goc theo log_ids).

Chay (xem README.md cung thu muc):
    pip install locust
    locust -f locustfile.py

So nguoi dung dong thoi (--users) va spawn rate cau hinh khi chay, KHONG
hardcode o day - moi lan do co the dung muc tai khac nhau.

Chay rieng mot nhom:
    locust -f locustfile.py IngestionUser
    locust -f locustfile.py QueryUser
"""

from __future__ import annotations

import logging
import os
import random
import re
from datetime import datetime, timezone

from locust import HttpUser, between, task
from locust.exception import StopUser

logger = logging.getLogger(__name__)

INGESTION_HOST = os.environ.get("INGESTION_HOST", "http://localhost:8000")
QUERY_API_HOST = os.environ.get("QUERY_API_HOST", "http://localhost:8002")

# So log moi request /ingest/batch. De nho de do overhead-per-request cua batch
# so voi /ingest don le, khong phai de do gioi han batch (server chan o
# INGEST_MAX_BATCH_SIZE, mac dinh 500).
BATCH_SIZE = int(os.environ.get("LOAD_TEST_BATCH_SIZE", "50"))

# So card Dashboard mo phong trong 1 lan mo trang. Moi card TU goi
# /clusters/{id}/history rieng (xem web/src/components/dashboard/ClusterCard.tsx),
# nen mo Dashboard mot lan = N request vao endpoint nay, khong phai 1.
# `GET /clusters` mac dinh tra toi 100 cum, tuc Dashboard that co the ban toi
# 100 request - de mac dinh 12 cho phep do co kiem soat, tang len khi can.
DASHBOARD_CARDS = int(os.environ.get("LOAD_TEST_DASHBOARD_CARDS", "12"))

# PATCH /clusters/{id} DOI TRANG THAI incident that tren moi truong dang do,
# nen tat mac dinh: bat co y bang LOAD_TEST_INCIDENT_WRITE=true.
INCIDENT_WRITE_ENABLED = os.environ.get(
    "LOAD_TEST_INCIDENT_WRITE", "").strip().lower() in {"true", "1", "yes"}

SERVICES = ("demo-web", "demo-mobile-api")

# Vai loai loi khac nhau de clustering co cai ma nhom, thay vi mot signature
# duy nhat lap lai (khi do chi sinh ra dung 1 cum, khong do duoc gi ve clustering).
ERRORS = (
    ("ValueError", "User {id} not found"),
    ("ConnectionError", "Database connection pool exhausted"),
    ("RuntimeError", "Simulated downstream failure"),
    ("TimeoutError", "Upstream timed out after {id} ms"),
)


def _now_iso() -> str:
    """Thoi diem HIEN TAI, khong phai moc co dinh.

    /search mac dinh chi tra 24h gan nhat va clustering chi xet cua so thoi
    gian hien tai, nen log gan moc co dinh se nam ngoai moi cua so -> do xong
    khong thay gi trong ket qua.
    """
    return datetime.now(timezone.utc).isoformat()


class IngestionUser(HttpUser):
    """Mo phong demo-app lien tuc gui log ve Ingestion Service."""

    wait_time = between(0.1, 0.5)
    host = INGESTION_HOST

    @task(7)
    def ingest_info_log(self):
        self.client.post("/ingest", json=self._payload("INFO", "Listed items successfully"),
                         name="POST /ingest (INFO)")

    @task(3)
    def ingest_error_log(self):
        exception, template = random.choice(ERRORS)
        message = template.format(id=random.randint(1000, 9999))
        payload = self._payload("ERROR", message)
        payload["stack_trace"] = f"Traceback (most recent call last):\n{exception}: {message}"
        self.client.post("/ingest", json=payload, name="POST /ingest (ERROR)")

    @task(2)
    def ingest_batch_logs(self):
        """POST /ingest/batch - body la JSON ARRAY (khong phai object bao ngoai).

        Do rieng voi /ingest de tra loi duoc cau hoi "batch giup gi": cung so
        log nhung it request hon, nen so sanh req/s va p95 cua dong nay voi
        `POST /ingest (INFO)` moi thay duoc phan overhead da tiet kiem.
        """
        batch = [self._payload("INFO", "Batch listed items successfully")
                 for _ in range(BATCH_SIZE)]
        self.client.post("/ingest/batch", json=batch,
                         name=f"POST /ingest/batch ({BATCH_SIZE} log)")

    @task(1)
    def ingest_invalid_log(self):
        """Log sai schema -> phai bi tu choi 400 va day sang quarantine.

        Dung `catch_response` vi 400 o day la KET QUA DUNG; neu khong Locust
        se tinh thanh loi va lam hong ty le loi cua ca phep do.
        """
        broken = {"timestamp": _now_iso(), "level": "CRITICAL", "service": "demo-web",
                  "message": "Load test malformed log"}  # thieu trace_id/span_id, level sai enum
        with self.client.post("/ingest", json=broken, name="POST /ingest (sai schema)",
                              catch_response=True) as response:
            if response.status_code == 400:
                response.success()
            else:
                response.failure(f"Mong doi 400, nhan {response.status_code}")

    @staticmethod
    def _payload(level: str, message: str) -> dict:
        return {
            "timestamp": _now_iso(),
            "level": level,
            "service": random.choice(SERVICES),
            "trace_id": f"{random.getrandbits(128):032x}",
            "span_id": f"{random.getrandbits(64):016x}",
            "message": message,
        }


class QueryUser(HttpUser):
    """Mo phong nguoi dung tra cuu log va xem Incident View."""

    wait_time = between(0.5, 2.0)
    host = QUERY_API_HOST

    def on_start(self):
        self.cluster_ids: list[str] = []
        self.client.headers.pop("Authorization", None)
        username = os.environ.get("QUERY_API_USERNAME")
        password = os.environ.get("QUERY_API_PASSWORD")
        if not username or not username.strip() or not password or not password.strip():
            logger.error("QueryUser requires QUERY_API_USERNAME and QUERY_API_PASSWORD; stopping user.")
            raise StopUser()

        failure = None
        token = None
        # X-CSRF-Protection la BAT BUOC voi moi POST /auth/* (xem
        # query-api/src/auth.py::protect_auth_post) - thieu header nay thi
        # login tra 403 chu khong phai 401, va ca nhom QueryUser dung ngay.
        # Khong gui Origin: request khong tu trinh duyet nen bo qua check origin.
        with self.client.post("/auth/login", json={"username": username, "password": password},
                              headers={"X-CSRF-Protection": "1"},
                              name="POST /auth/login", catch_response=True) as response:
            if response.status_code != 200:
                failure = f"Query API login failed (HTTP {response.status_code}); stopping user."
            else:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                token = body.get("token") if isinstance(body, dict) else None
                # Chi kiem tra shape JWT ky; khong dua JWT_SECRET vao load-test client.
                if (not isinstance(token, str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)):
                    failure = "Query API login returned an invalid JWT response; stopping user."
            if failure:
                response.failure(failure)

        # Thoat context truoc StopUser de login that bai van duoc ghi vao Locust statistics.
        if failure:
            logger.error(failure)
            raise StopUser()
        self.client.headers["Authorization"] = f"Bearer {token}"

    @task(5)
    def search_logs(self):
        self.client.get("/search", params={"limit": 50}, name="GET /search")

    @task(3)
    def search_with_filter(self):
        self.client.get("/search", name="GET /search (co filter)", params={
            "service": random.choice(SERVICES), "q": "failed", "limit": 50,
        })

    @task(3)
    def list_clusters(self):
        """Liet ke cum, dong thoi nho lai id de buoc Incident View dung id that."""
        with self.client.get("/clusters", name="GET /clusters", catch_response=True) as response:
            if response.status_code != 200:
                return
            clusters = response.json().get("clusters", [])
            self.cluster_ids = [c["cluster_id"] for c in clusters if c.get("cluster_id")]

    @task(2)
    def incident_view(self):
        """Buoc nang nhat: doc cum roi keo toan bo log goc theo log_ids.

        Bo qua khi chua co cum nao (dau phep do, clustering chua chay xong) -
        khong goi id gia de khoi tao ra 404 lam nhieu ty le loi.
        """
        if not self.cluster_ids:
            return
        cluster_id = random.choice(self.cluster_ids)
        self.client.get(f"/clusters/{cluster_id}", name="GET /clusters/{id}")

    @task(2)
    def search_aggregations(self):
        """Histogram + facet cua trang Search.

        Do rieng voi /search: endpoint nay chay aggregation (date_histogram +
        2 terms agg) thay vi chi lay N log dau, nen chi phi khac han - gop
        chung mot dong thong ke se che mat endpoint nao that su cham.
        """
        self.client.get("/search/aggregations", name="GET /search/aggregations", params={
            "interval": "hour", "service": random.choice(SERVICES),
        })

    @task(2)
    def dashboard_sparklines(self):
        """Mo phong MOT lan mo Dashboard, khong phai mot request le.

        Moi card goi /clusters/{id}/history rieng nen day la N request lien
        tiep. Do nhu vay moi thay duoc tai that cua trang Dashboard; neu chi
        goi 1 lan/task thi so do khong phan anh gi.
        """
        if not self.cluster_ids:
            return
        for cluster_id in self.cluster_ids[:DASHBOARD_CARDS]:
            self.client.get(f"/clusters/{cluster_id}/history",
                            name="GET /clusters/{id}/history")

    @task(1)
    def acknowledge_incident(self):
        """PATCH /clusters/{id} - chi chay khi LOAD_TEST_INCIDENT_WRITE=true.

        Tat mac dinh vi no DOI TRANG THAI incident that: chay tren ban deploy
        se lam cac cum dang `open` thanh `acknowledged`, lam nhieu du lieu demo.

        409 la KET QUA DUNG o day, khong phai loi: nhieu user ao cung ack mot
        cum, hoac dot (`episode_id`) da doi trang thai giua luc doc va luc ghi
        -> CAS tu choi dung nhu thiet ke. Tinh thanh loi se lam hong ty le loi
        cua ca phep do.
        """
        if not INCIDENT_WRITE_ENABLED or not self.cluster_ids:
            return
        cluster_id = random.choice(self.cluster_ids)
        response = self.client.get(f"/clusters/{cluster_id}",
                                   name="GET /clusters/{id} (truoc ack)")
        if response.status_code != 200:
            return
        incident = (response.json() or {}).get("incident") or {}
        # Chi ack dot dang mo; dot da acknowledged/resolved thi PATCH chi tao
        # them 409 vo nghia, khong do duoc gi ve duong ghi.
        if incident.get("status") != "open" or not incident.get("episode_id"):
            return
        with self.client.patch(
            f"/clusters/{cluster_id}",
            json={"episode_id": incident["episode_id"], "action": "acknowledge"},
            name="PATCH /clusters/{id} (acknowledge)", catch_response=True,
        ) as response:
            if response.status_code in (200, 409):
                response.success()
            else:
                response.failure(f"Mong doi 200 hoac 409, nhan {response.status_code}")
