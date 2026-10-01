"""
Load test cho Log Anomaly Explorer, dung Locust.

Chay thu:
    pip install locust
    locust -f locustfile.py --host http://localhost:8000

So nguoi dung dong thoi (concurrency) cau hinh khi chay Locust (--users),
KHONG hardcode trong file nay - moi lan test co the dung muc tai khac nhau
tuy muc tieu (vd. theo yeu cau cua bien the ca nhan dang lam).

TODO (Minh): bo sung task gui /ingest voi du lieu thuc.
TODO (Nghia): bo sung task goi /search, /clusters, /clusters/{id} cho load test end-to-end.
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task


class IngestionUser(HttpUser):
    """Mo phong demo-app lien tuc gui log ve Ingestion Service."""

    wait_time = between(0.1, 0.5)
    host = "http://localhost:8000"

    @task
    def ingest_log(self):
        payload = {
            "timestamp": "2026-10-01T09:00:00Z",
            "level": random.choice(["INFO", "WARN", "ERROR"]),
            "service": "demo-web",
            "trace_id": f"trace-{random.randint(1, 100000)}",
            "span_id": f"span-{random.randint(1, 100000)}",
            "message": "Load test log entry",
        }
        self.client.post("/ingest", json=payload)


class QueryUser(HttpUser):
    """Mo phong nguoi dung / doi tac goi Query & Incident API."""

    wait_time = between(0.5, 2.0)
    host = "http://localhost:8002"

    @task
    def list_clusters(self):
        self.client.get("/clusters")
