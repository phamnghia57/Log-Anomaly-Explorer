"""VT-014 - test muc API (FastAPI TestClient): header Idempotency-Key -> HTTP response.

Can FastAPI + httpx (requirements-dev.txt). Moi truong thieu thu vien -> SKIP co ly do
(khong fail gia). CI GitHub Actions (.github/workflows/tests.yml) cai du va chay file nay.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from ingestion.src import main  # noqa: E402
from ingestion.src.idempotency import IdempotencyStore  # noqa: E402
from ingestion.src.storage import InMemoryLogStore  # noqa: E402


def make_log(**over):
    log = {"timestamp": "2026-11-10T08:00:00Z", "level": "ERROR", "service": "demo-web",
           "trace_id": "t1", "span_id": "s1", "message": "Simulated failure"}
    log.update(over)
    return log


@pytest.fixture
def client():
    # Reset TOAN BO trang thai module-level -> khong phu thuoc thu tu chay test
    main.store = InMemoryLogStore()
    main.idempotency = IdempotencyStore(ttl_seconds=60)
    main.limiter = main.SlidingWindowRateLimiter(1000)
    with TestClient(main.app) as c:
        yield c


def test_tc16_api_replay_same_body_and_header(client):
    h = {"Idempotency-Key": "api-0001"}
    a = client.post("/ingest", json=make_log(), headers=h)
    b = client.post("/ingest", json=make_log(), headers=h)
    assert a.status_code == b.status_code == 202
    assert a.json() == b.json()
    assert "idempotent-replayed" not in a.headers
    assert b.headers["idempotent-replayed"] == "true"
    assert len(main.store._logs) == 1
    assert list(main.store._logs) == [a.json()["log_id"]]


def test_tc16b_api_invalid_key_and_reuse(client):
    assert client.post("/ingest", json=make_log(), headers={"Idempotency-Key": "a" * 129}).status_code == 400
    client.post("/ingest", json=make_log(), headers={"Idempotency-Key": "api-0002"})
    r = client.post("/ingest", json=make_log(message="x"), headers={"Idempotency-Key": "api-0002"})
    assert r.status_code == 409 and r.json()["reason"] == "idempotency_key_reused"


def test_tc16c_api_batch_replay(client):
    h = {"Idempotency-Key": "api-batch-1"}
    batch = [make_log(trace_id="a"), make_log(trace_id="b")]
    a = client.post("/ingest/batch", json=batch, headers=h)
    b = client.post("/ingest/batch", json=batch, headers=h)
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert len(main.store._logs) == 2


def test_tc16d_api_without_key_unchanged(client):
    a = client.post("/ingest", json=make_log())
    b = client.post("/ingest", json=make_log())
    assert a.json()["log_id"] != b.json()["log_id"] and len(main.store._logs) == 2
