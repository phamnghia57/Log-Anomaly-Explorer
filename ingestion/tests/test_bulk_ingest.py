"""
Test cho POST /ingest/bulk - change request VT-016:
"Them chuc nang import du lieu hang loat; ban ghi loi khong duoc lam mat cac ban ghi hop le."

Viet TRUOC khi co code (TDD: Red -> Green). Dung ca test vi du (example-based)
lan property-based testing (Hypothesis) - xem README.md phan "Test strategy"
de biet ly do chon ky thuat nay va cach chon test data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ingestion.src import main
from ingestion.src.storage import InMemoryLogStore, StorageError

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
MAX_BATCH_SIZE = 500  # phai khop voi gioi han thuc te trong main.py (NFR: bao ve p95)


def iso(delta_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_log(**over) -> dict:
    log = {"timestamp": iso(), "level": "ERROR", "service": "demo-web",
           "trace_id": "t1", "span_id": "s1", "message": "Simulated failure in checkout"}
    log.update(over)
    return log


@pytest.fixture
def client():
    main.store = InMemoryLogStore()
    with TestClient(main.app) as c:
        yield c


# --------------------------------------------------------------------------- example-based

def test_bulk_accepts_all_valid_logs_and_they_are_searchable(client):
    logs = [make_log(trace_id=f"t{i}") for i in range(5)]
    r = client.post("/ingest/bulk", json={"logs": logs})
    assert r.status_code == 207
    body = r.json()
    assert body["accepted"] == 5 and body["quarantined"] == 0 and body["failed"] == 0
    assert len(body["results"]) == 5
    assert all(item["status"] == "accepted" and item["log_id"] for item in body["results"])
    assert main.store.search(limit=10).__len__() == 5  # that su nam trong store, khong chi response noi vay


def test_bulk_mixed_batch_quarantines_invalid_without_losing_valid_records(client):
    """AC2 (cot loi cua change request): 1 ban ghi loi KHONG duoc lam mat cac ban ghi hop le khac."""
    logs = [
        make_log(trace_id="ok-1"),
        {"level": "ERROR"},  # thieu required fields -> sai schema
        make_log(trace_id="ok-2"),
        make_log(timestamp="not-a-date", trace_id="ok-3"),  # timestamp hong -> sai schema
        make_log(trace_id="ok-4"),
    ]
    r = client.post("/ingest/bulk", json={"logs": logs})
    assert r.status_code == 207
    body = r.json()
    assert body["accepted"] == 3 and body["quarantined"] == 2 and body["failed"] == 0

    statuses = [item["status"] for item in body["results"]]
    assert statuses == ["accepted", "quarantined", "accepted", "quarantined", "accepted"]

    stored = main.store.search(limit=10)
    assert {l["trace_id"] for l in stored} == {"ok-1", "ok-2", "ok-4"}  # ca 3 ban ghi hop le con du, khong mat
    assert len(main.store._quarantine) == 2  # 2 ban loi di dung duong quarantine, khong lot vao index chinh


def test_bulk_persistence_failure_never_reported_as_accepted(client, monkeypatch):
    """Invariant quan trong nhat (xem README.md): KHONG BAO GIO bao accepted=true cho ban ghi
    ma viec ghi (persistence) that bai thuc su. Day chinh la test bat duoc mutation o muc 4."""
    logs = [make_log(trace_id=f"t{i}") for i in range(5)]
    original_write = main.store.write_log

    def flaky_write(log_id, log):
        if log["trace_id"] == "t2":
            raise StorageError("simulated disk full")
        return original_write(log_id, log)

    monkeypatch.setattr(main.store, "write_log", flaky_write)

    r = client.post("/ingest/bulk", json={"logs": logs})
    assert r.status_code == 207
    body = r.json()
    results = body["results"]

    assert results[2]["status"] == "failed"
    assert results[2]["status"] != "accepted"  # <-- dong khang dinh trung tam cua invariant
    assert "log_id" not in results[2] or results[2].get("log_id") is None

    accepted_indexes = [item["index"] for item in results if item["status"] == "accepted"]
    assert accepted_indexes == [0, 1, 3, 4]  # 4 ban ghi con lai KHONG bi mat vi 1 ban ghi loi o giua
    assert body["accepted"] == 4 and body["failed"] == 1

    stored_trace_ids = {l["trace_id"] for l in main.store.search(limit=10)}
    assert stored_trace_ids == {"t0", "t1", "t3", "t4"}  # that su co trong store, khong chi response


# --------------------------------------------------------------------------- negative tests (>= 2)

def test_bulk_rejects_empty_batch(client):
    r = client.post("/ingest/bulk", json={"logs": []})
    assert r.status_code == 400


def test_bulk_rejects_batch_over_max_size(client):
    logs = [make_log(trace_id=f"t{i}") for i in range(MAX_BATCH_SIZE + 1)]
    r = client.post("/ingest/bulk", json={"logs": logs})
    assert r.status_code == 400
    assert main.store.search(limit=10).__len__() == 0  # tu choi ca batch, khong ghi mot phan


def test_single_ingest_unaffected_by_bulk_feature(client):
    """Risk trong tam cua VT-016: thay doi nho khong duoc lam hong behavior cu khong lien quan.
    Test lai nguyen van hanh vi cua POST /ingest (khong phai bulk) sau khi them tinh nang moi."""
    r = client.post("/ingest", json=make_log())
    assert r.status_code == 202
    assert r.json()["accepted"] is True


# --------------------------------------------------------------------------- property-based testing

# Chi sinh log HOP LE theo dung log-schema.json (service/level theo dung tap gia tri
# thuc te dang dung trong demo-app, trace_id/span_id dang hex nhu OpenTelemetry sinh ra).
_valid_logs = st.builds(
    lambda level, service, trace_id, span_id, message: {
        "timestamp": iso(), "level": level, "service": service,
        "trace_id": trace_id, "span_id": span_id, "message": message,
    },
    level=st.sampled_from(LEVELS),
    service=st.sampled_from(["demo-web", "demo-mobile-api"]),
    trace_id=st.text(alphabet="0123456789abcdef", min_size=8, max_size=32),
    span_id=st.text(alphabet="0123456789abcdef", min_size=4, max_size=16),
    message=st.text(min_size=1, max_size=120).filter(lambda s: s.strip() != ""),
)


def _invalid_missing_fields() -> dict:
    return {"level": "ERROR"}


def _invalid_bad_timestamp() -> dict:
    return {"timestamp": "not-a-date", "level": "ERROR", "service": "demo-web",
            "trace_id": "a", "span_id": "b", "message": "m"}


def _invalid_bad_level_enum() -> dict:
    return {"timestamp": iso(), "level": "TRACE", "service": "demo-web",
            "trace_id": "a", "span_id": "b", "message": "m"}


_invalid_logs = st.sampled_from(
    [_invalid_missing_fields, _invalid_bad_timestamp, _invalid_bad_level_enum]
).map(lambda build: build())

_tagged_item = st.one_of(
    _valid_logs.map(lambda d: ("valid", d)),
    _invalid_logs.map(lambda d: ("invalid", d)),
)


@given(items=st.lists(_tagged_item, min_size=1, max_size=25))
@settings(
    max_examples=50,
    deadline=None,
    # Hypothesis canh bao (dung, da tu bat duoc khi viet test nay - xem README.md
    # muc "Flaky test review"): fixture `client` la function-scoped nen KHONG duoc
    # tao lai giua cac vi du cua @given. O day an toan de bo qua canh bao vi trang
    # thai thuc su quan trong (main.store) da duoc reset THU CONG o dong dau than ham;
    # TestClient chi la wrapper HTTP khong mang trang thai nghiep vu.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_property_valid_records_never_lost_regardless_of_batch_composition(client, items):
    """Property can chung minh (dung thay vi liet ke tung truong hop cu the):
    'Voi BAT KY to hop nao (so luong, thu tu) giua log hop le va log sai schema trong 1 batch,
    so log hop le duoc luu lai dung bang so log hop le dua vao - khong hon, khong kem.'

    Day la dung property-based testing vi khong gian dau vao la moi hoan vi/to hop
    hop le-vs-loi ma vi du don le khong bao quat het duoc.
    """
    main.store = InMemoryLogStore()  # Hypothesis goi lai than ham nhieu lan -> phai reset state moi vi du

    payload = {"logs": [item for _, item in items]}
    expected_valid = sum(1 for kind, _ in items if kind == "valid")

    r = client.post("/ingest/bulk", json=payload)

    assert r.status_code == 207
    body = r.json()
    assert body["accepted"] == expected_valid
    assert body["accepted"] + body["quarantined"] == len(items)

    stored = main.store.search(limit=1000)
    assert len(stored) == expected_valid  # bat bien cot loi: khong mat, khong thua
