"""Tao MOT bat thuong that de kiem duong canh bao (#102 tieu chi 3).

Bom N log ERROR cung mot signature MOI vao DUNG mot cua so 60s qua chinh
POST /ingest/batch. Signature moi -> baseline 0 -> score ~ so log trong cua so
cuoi / do lech chuan, vuot nguong 3.0.

Chay trong container clustering hoac query-api:
    python /tmp/make_anomaly.py [so_log]
"""
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 60
SERVICE = "alert-path-test"
MESSAGE = "Simulated alert path check: deliberate webhook failure drill"

# Dat moc o dau phut hien tai, roi rai trong 50s -> tat ca nam trong CUNG mot
# cua so 60s ma worker chua xu ly.
minute_start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
batch = [{
    "timestamp": (minute_start + timedelta(seconds=i % 50)).isoformat().replace("+00:00", "Z"),
    "level": "ERROR",
    "service": SERVICE,
    "trace_id": uuid.uuid4().hex,
    "span_id": uuid.uuid4().hex[:16],
    "message": MESSAGE,
    "stack_trace": "RuntimeError: deliberate drill for alert delivery failure\n  at drill.py:1",
} for i in range(COUNT)]

started = time.time()
response = httpx.post("http://ingestion:8000/ingest/batch", json=batch, timeout=60)
response.raise_for_status()
print("service        =", SERVICE)
print("so log bom     =", COUNT)
print("cua so         =", minute_start.isoformat(), "->",
      (minute_start + timedelta(seconds=60)).isoformat())
print("ingest tra ve  =", response.status_code, response.json())
print("mat            = %.2fs" % (time.time() - started))
