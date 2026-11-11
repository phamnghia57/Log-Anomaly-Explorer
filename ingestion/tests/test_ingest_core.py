"""Characterization tests cho ingest_core (tach tu main.py, khong doi hanh vi).

Chay KHONG can FastAPI: `cd ingestion && python -m pytest tests/test_ingest_core.py`.
Muc tieu: khoa hanh vi baseline (commit 33515bd) truoc khi them idempotency.
"""

from datetime import datetime, timezone

from ingestion.src.ingest_core import process_batch, process_single
from ingestion.src.storage import InMemoryLogStore


def make_log(**over):
    log = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "level": "ERROR", "service": "demo-web", "trace_id": "t1", "span_id": "s1",
           "message": "Simulated failure in checkout"}
    log.update(over)
    return log


def test_single_valid_is_202_and_stored():
    store = InMemoryLogStore()
    r = process_single(store, make_log())
    assert r.status == 202 and r.body["accepted"] is True
    assert [d["log_id"] for d in store.get_logs([r.body["log_id"]])] == [r.body["log_id"]]


def test_single_invalid_is_400_and_quarantined_only():
    store = InMemoryLogStore()
    r = process_single(store, {"level": "ERROR"})
    assert r.status == 400 and r.body["reason"] == "schema_validation_failed"
    assert len(store._quarantine) == 1 and store._logs == {}


def test_batch_all_or_nothing_and_size_limit():
    store = InMemoryLogStore()
    assert process_batch(store, [], 500).status == 400
    assert process_batch(store, [make_log()] * 3, 2).status == 400
    bad = process_batch(store, [make_log(), {"level": "ERROR"}], 500)
    assert bad.status == 400 and bad.body["errors"][0]["index"] == 1 and store._logs == {}
    ok = process_batch(store, [make_log(trace_id="a"), make_log(trace_id="b")], 500)
    assert ok.status == 202 and ok.body["accepted_count"] == 2 and len(store._logs) == 2


def test_baseline_resubmit_creates_duplicate():
    """CHARACTERIZATION cua loi ma change request VT-014 can sua:
    gui lai CUNG payload -> sinh UUID moi -> 2 ban ghi trung."""
    store = InMemoryLogStore()
    payload = make_log()
    a = process_single(store, payload)
    b = process_single(store, payload)
    assert a.body["log_id"] != b.body["log_id"]
    assert len(store._logs) == 2
