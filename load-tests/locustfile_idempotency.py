"""VT-014 - Locust cho stack THAT: gui log kem Idempotency-Key roi gui lai (retry).

File rieng (khong sua locustfile.py chung cua nhom) -> lenh `locust -f locustfile.py`
cu khong bi them user moi.

    # Rate limit mac dinh 100 RPS/process -> 150 user se nhan 429. Khi do tai cho p95:
    INGEST_RATE_LIMIT_RPS=2000 docker compose up -d ingestion
    locust -f locustfile_idempotency.py --headless --users 150 --spawn-rate 30 \
           --run-time 3m --csv ket-qua-vt014 --host http://localhost:8000

Danh gia: p95 cot "95%" trong ket-qua-vt014_stats.csv <= 4000 ms; "Failure Count" = 0
(failure bao gom: replay tra log_id khac lan dau, thieu header Idempotent-Replayed).
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import datetime, timezone

from locust import HttpUser, between, task

INGESTION_HOST = os.environ.get("INGESTION_HOST", "http://localhost:8000")


class IdempotentRetryUser(HttpUser):
    wait_time = between(0.1, 0.5)
    host = INGESTION_HOST

    def _payload(self) -> dict:
        return {"timestamp": datetime.now(timezone.utc).isoformat(), "level": "ERROR",
                "service": "demo-web", "trace_id": f"{random.getrandbits(128):032x}",
                "span_id": f"{random.getrandbits(64):016x}", "message": "VT-014 retry load"}

    @task
    def submit_then_retry(self):
        payload, key = self._payload(), f"vt014-{uuid.uuid4()}"
        headers = {"Idempotency-Key": key}
        first = self.client.post("/ingest", json=payload, headers=headers,
                                 name="POST /ingest (idempotent, lan dau)")
        if first.status_code != 202:
            return
        for _ in range(2):
            with self.client.post("/ingest", json=payload, headers=headers, catch_response=True,
                                  name="POST /ingest (idempotent, gui lai)") as again:
                if again.status_code != 202:
                    again.failure(f"replay status {again.status_code}")
                elif again.json().get("log_id") != first.json().get("log_id"):
                    again.failure("replay tra log_id khac -> co the tao du lieu trung")
                elif again.headers.get("Idempotent-Replayed") != "true":
                    again.failure("thieu header Idempotent-Replayed")
                else:
                    again.success()
