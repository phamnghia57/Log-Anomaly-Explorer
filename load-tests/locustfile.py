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
        with self.client.post("/auth/login", json={"username": username, "password": password},
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
