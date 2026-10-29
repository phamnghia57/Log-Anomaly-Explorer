"""
Harness do tai rieng cho VT-016: POST /ingest/bulk o 200 nguoi dung/tac vu dong thoi,
muc tieu p95 <= 5.0 giay.

KHONG phai load-tests/locustfile.py cua ca nhom (file do danh cho toan he thong qua
OpenSearch that). File nay la harness RIENG cho bai tap ca nhan, dung STORAGE_BACKEND=memory
vi moi truong lam bai khong co Docker/OpenSearch song (xem README.md "Gioi han" de biet
ket luan nay ap dung duoc toi dau).

Chay (xem README.md muc "Load test"):
    cd ingestion
    STORAGE_BACKEND=memory RETENTION_INTERVAL_SECONDS=0 python -m uvicorn src.main:app --port 8010 &
    locust -f ../docs/task/evidence/vt-016/load_test_bulk.py --headless \
           --users 200 --spawn-rate 50 --run-time 1m \
           --csv ../docs/task/evidence/vt-016/04-load-test
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timezone

from locust import HttpUser, between, task

HOST = os.environ.get("BULK_TARGET_HOST", "http://127.0.0.1:8010")
BATCH_SIZE = int(os.environ.get("BULK_BATCH_SIZE", "10"))  # nho, mo phong client goi thuong xuyen


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_log(i: int) -> dict:
    return {
        "timestamp": _now_iso(),
        "level": random.choice(["INFO", "WARN", "ERROR"]),
        "service": random.choice(["demo-web", "demo-mobile-api"]),
        "trace_id": f"{random.getrandbits(128):032x}",
        "span_id": f"{random.getrandbits(64):016x}",
        "message": f"bulk load test record {i}",
    }


class BulkImportUser(HttpUser):
    """Mo phong mot client goi import hang loat lien tuc (VT-016)."""

    wait_time = between(0.1, 0.5)
    host = HOST

    @task
    def ingest_bulk(self):
        payload = {"logs": [_make_log(i) for i in range(BATCH_SIZE)]}
        with self.client.post("/ingest/bulk", json=payload, name="POST /ingest/bulk",
                              catch_response=True) as response:
            if response.status_code == 207:
                response.success()
            else:
                response.failure(f"mong doi 207, nhan {response.status_code}")
