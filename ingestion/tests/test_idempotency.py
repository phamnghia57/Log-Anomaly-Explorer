"""VT-014: gui lai cung yeu cau KHONG tao du lieu trung (Idempotency-Key).

Ky thuat thiet ke test: EQUIVALENCE PARTITIONING tren 4 bien dau vao
  K  = header Idempotency-Key : K0 vang | K1 hop le | K2 khong hop le
  H  = quan he voi lich su    : H1 chua thay | H2 da thay + cung payload
                                | H3 da thay + khac payload | H4 da het han
                                | H5 lan truoc loi storage | H6 dang xu ly song song
  P  = payload                 : P1 hop le | P2 sai schema
  E  = endpoint                : /ingest | /ingest/batch
Moi test ghi ro lop tuong duong + ID test case (TC-xx) trong bao cao.

Chay KHONG can FastAPI/mang/dong ho that:
    cd ingestion && python -m pytest tests/test_idempotency.py -v
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from ingestion.src.idempotency import IdempotencyStore
from ingestion.src.ingest_core import handle_ingest, handle_ingest_batch
from ingestion.src.storage import InMemoryLogStore, OpenSearchLogStore, StorageError

REPLAY = "Idempotent-Replayed"
FIXED_TS = "2026-11-10T08:00:00Z"  # co dinh -> khong phu thuoc gio chay test


def make_log(**over):
    log = {"timestamp": FIXED_TS, "level": "ERROR", "service": "demo-web",
           "trace_id": "t1", "span_id": "s1", "message": "Simulated failure in checkout"}
    log.update(over)
    return log


class FakeClock:
    """Dong ho gia: test TTL khong dung time.sleep (tranh flaky theo thoi gian)."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def store():
    return InMemoryLogStore()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def idem(clock):
    # Moi test mot instance moi -> khong chia se trang thai giua cac test
    return IdempotencyStore(ttl_seconds=60, clock=clock)


# ---------------------------------------------------------------- K0: vang key
def test_tc01_no_key_keeps_legacy_behavior(store, idem):
    """K0+P1: khong gui header -> hanh vi cu (UUID moi moi lan), tuong thich nguoc."""
    a = handle_ingest(store, idem, make_log(), None)
    b = handle_ingest(store, idem, make_log(), None)
    assert a.status == b.status == 202
    assert a.body["log_id"] != b.body["log_id"]
    assert len(store._logs) == 2
    assert REPLAY not in a.headers and REPLAY not in b.headers


# ---------------------------------------------------------------- K1 x H1/H2
def test_tc02_new_valid_key_writes_once_and_maps_log_id(store, idem):
    """K1+H1+P1: key moi -> 202, ghi 1 ban ghi; log_id trong response tro dung document."""
    r = handle_ingest(store, idem, make_log(), "order-7f3a-0001")
    assert r.status == 202 and r.body["accepted"] is True
    assert REPLAY not in r.headers
    stored = store.get_logs([r.body["log_id"]])
    assert len(stored) == 1 and stored[0]["trace_id"] == "t1"
    assert len(store._logs) == 1


def test_tc03_replay_same_payload_returns_identical_response(store, idem):
    """K1+H2+P1: gui lai 3 lan -> 1 ban ghi, cung status/body, header replay."""
    first = handle_ingest(store, idem, make_log(), "order-7f3a-0002")
    replays = [handle_ingest(store, idem, make_log(), "order-7f3a-0002") for _ in range(3)]
    assert len(store._logs) == 1
    for r in replays:
        assert r.status == first.status == 202
        assert r.body == first.body
        assert r.headers.get(REPLAY) == "true"


def test_tc04_same_payload_different_key_order_is_same_request(store, idem):
    """H2: thu tu field JSON khac nhung noi dung giong -> cung lop 'cung payload'."""
    p1 = make_log()
    p2 = dict(reversed(list(p1.items())))
    a = handle_ingest(store, idem, p1, "k-order")
    b = handle_ingest(store, idem, p2, "k-order")
    assert b.status == 202 and b.body == a.body and b.headers.get(REPLAY) == "true"
    assert len(store._logs) == 1


# ---------------------------------------------------------------- K1 x H3 (negative)
def test_tc05_same_key_different_payload_is_409_without_write(store, idem):
    """NEGATIVE K1+H3: tai su dung key cho payload khac -> 409, khong ghi, khong quarantine."""
    handle_ingest(store, idem, make_log(), "k-reuse")
    r = handle_ingest(store, idem, make_log(message="another failure"), "k-reuse")
    assert r.status == 409
    assert r.body["accepted"] is False and r.body["reason"] == "idempotency_key_reused"
    assert len(store._logs) == 1 and store._quarantine == []


# ---------------------------------------------------------------- K2 (negative) + bien
@pytest.mark.parametrize("bad_key", ["", "   ", "a" * 129, "abc def", "khóa-1", "<script>"],
                         ids=["empty", "blank", "len129", "space", "non-ascii", "html"])
def test_tc06_invalid_key_rejected_before_any_write(store, idem, bad_key):
    """NEGATIVE K2: key sai dinh dang -> 400 invalid_idempotency_key, kho khong doi."""
    r = handle_ingest(store, idem, make_log(), bad_key)
    assert r.status == 400 and r.body["reason"] == "invalid_idempotency_key"
    assert store._logs == {} and store._quarantine == []


@pytest.mark.parametrize("edge_key", ["a", "a" * 128, "A-z_0.9:x"], ids=["len1", "len128", "charset"])
def test_tc07_boundary_valid_keys_accepted(store, idem, edge_key):
    """K1 bien: do dai 1 va 128, du bo ky tu cho phep -> hop le."""
    assert handle_ingest(store, idem, make_log(), edge_key).status == 202


# ---------------------------------------------------------------- H5: failure path
def test_tc08_storage_failure_is_not_remembered_and_retry_writes_once(store, idem, monkeypatch):
    """FAILURE PATH H5: lan 1 storage loi -> StorageError (main.py map 503), KHONG luu ket qua;
    retry cung key -> xu ly that, dung 1 ban ghi, khong bi 'ket' o trang thai loi."""
    real_write = store.write_log
    calls = {"n": 0}

    def flaky_write(log_id, log):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StorageError("opensearch timeout")
        real_write(log_id, log)

    monkeypatch.setattr(store, "write_log", flaky_write)
    with pytest.raises(StorageError):
        handle_ingest(store, idem, make_log(), "k-retry")
    r = handle_ingest(store, idem, make_log(), "k-retry")
    assert r.status == 202 and REPLAY not in r.headers
    assert len(store._logs) == 1


def test_tc09_invalid_payload_replay_does_not_duplicate_quarantine(store, idem):
    """K1+P2: payload sai schema -> 400 lan dau; gui lai cung key -> 400 replay,
    quarantine chi co 1 ban ghi (quarantine cung la du lieu, khong duoc trung)."""
    bad = {"level": "ERROR"}
    a = handle_ingest(store, idem, bad, "k-bad")
    b = handle_ingest(store, idem, bad, "k-bad")
    assert a.status == b.status == 400 and b.body == a.body
    assert b.headers.get(REPLAY) == "true"
    assert len(store._quarantine) == 1


# ---------------------------------------------------------------- E: batch + cross endpoint
def test_tc10_batch_replay_writes_batch_once(store, idem):
    """E=/ingest/batch, K1+H2: gui lai batch -> khong ghi them, cung response."""
    batch = [make_log(trace_id="a"), make_log(trace_id="b")]
    first = handle_ingest_batch(store, idem, batch, "batch-0001", 500)
    again = handle_ingest_batch(store, idem, batch, "batch-0001", 500)
    assert first.status == again.status == 202
    assert again.body == first.body and again.headers.get(REPLAY) == "true"
    assert len(store._logs) == 2


def test_tc10b_batch_log_ids_map_to_payload_positions(store, idem):
    """BO SUNG SAU MUTATION M2 (song sot): log_ids[i] PHAI tro toi document cua payload[i]
    - ca lan dau lan replay. TC-10 chi so sanh replay voi lan dau nen khong bat duoc."""
    batch = [make_log(trace_id="first"), make_log(trace_id="second"), make_log(trace_id="third")]
    for _ in range(2):  # lan dau + replay
        r = handle_ingest_batch(store, idem, batch, "batch-map", 500)
        traces = [store.get_logs([log_id])[0]["trace_id"] for log_id in r.body["log_ids"]]
        assert traces == ["first", "second", "third"]
        assert r.body["accepted_count"] == len(r.body["log_ids"]) == 3


def test_tc08b_batch_partial_write_then_retry_has_no_duplicates(store, idem, monkeypatch):
    """FAILURE PATH (README cu: 'Bulk co the da ghi mot phan, retry khong idempotent'):
    lan 1 ghi duoc item 0 roi loi; retry cung key -> dung 2 document, khong trung item 0."""
    real_write = store.write_log
    state = {"calls": 0}

    def fail_on_second(log_id, log):
        state["calls"] += 1
        if state["calls"] == 2:
            raise StorageError("bulk partially failed")
        real_write(log_id, log)

    monkeypatch.setattr(store, "write_log", fail_on_second)
    batch = [make_log(trace_id="a"), make_log(trace_id="b")]
    with pytest.raises(StorageError):
        handle_ingest_batch(store, idem, batch, "batch-partial", 500)
    assert len(store._logs) == 1  # da ghi mot phan
    r = handle_ingest_batch(store, idem, batch, "batch-partial", 500)
    assert r.status == 202 and len(store._logs) == 2


def test_tc11_same_key_on_other_endpoint_is_409(store, idem):
    """NEGATIVE: cung key dung cho /ingest roi /ingest/batch -> xem la khac yeu cau -> 409."""
    handle_ingest(store, idem, make_log(), "k-cross")
    r = handle_ingest_batch(store, idem, [make_log()], "k-cross", 500)
    assert r.status == 409 and len(store._logs) == 1


# ---------------------------------------------------------------- H4: TTL (fake clock)
def test_tc12_expired_key_is_processed_again_but_still_no_duplicate(store, idem, clock):
    """H4: qua TTL -> key duoc xu ly lai (khong co header replay), NHUNG log_id tat dinh
    theo (endpoint, key, payload) nen kho van chi co 1 ban ghi."""
    a = handle_ingest(store, idem, make_log(), "k-ttl")
    clock.now += 61  # > ttl 60s, khong sleep
    b = handle_ingest(store, idem, make_log(), "k-ttl")
    assert REPLAY not in b.headers
    assert b.body["log_id"] == a.body["log_id"]
    assert len(store._logs) == 1


def test_tc12b_key_still_valid_just_before_ttl(store, idem, clock):
    """H2 bien TTL: con 1 giay truoc khi het han -> van replay."""
    handle_ingest(store, idem, make_log(), "k-ttl2")
    clock.now += 59
    assert handle_ingest(store, idem, make_log(), "k-ttl2").headers.get(REPLAY) == "true"


# ---------------------------------------------------------------- H6: concurrency
class CountingStore(InMemoryLogStore):
    """Dem so lan ghi va lam cham write_log de mo rong cua so race."""

    def __init__(self):
        super().__init__()
        self.writes = 0
        self._count_lock = threading.Lock()

    def write_log(self, log_id, log):
        with self._count_lock:
            self.writes += 1
        time.sleep(0.005)
        super().write_log(log_id, log)


def test_tc13_150_concurrent_identical_requests_write_once(idem):
    """H6: 150 request dong thoi cung key + payload -> dung 1 lan ghi, moi response 202
    va cung log_id (muc tai VT-014)."""
    store = CountingStore()
    barrier = threading.Barrier(150)

    def send(_):
        barrier.wait()
        return handle_ingest(store, idem, make_log(), "k-concurrent")

    with ThreadPoolExecutor(max_workers=150) as pool:
        results = list(pool.map(send, range(150)))
    assert store.writes == 1
    assert {r.status for r in results} == {202}
    assert len({r.body["log_id"] for r in results}) == 1
    assert sum(1 for r in results if r.headers.get(REPLAY) == "true") == 149


def test_tc13b_first_concurrent_request_fails_waiters_are_not_stuck(idem):
    """H5 x H6 (lo ra tu phan tich branch coverage cua khoi finally): request dau tien
    loi storage trong khi 19 request trung dang cho -> dung 1 request nhan loi, mot
    request khac ghi thanh cong, phan con lai replay; khong ai bi ket, khong trung."""

    class FailFirstStore(CountingStore):
        def write_log(self, log_id, log):
            with self._count_lock:
                self.writes += 1
                first = self.writes == 1
            if first:
                time.sleep(0.02)  # giu khoa de cac request khac xep hang
                raise StorageError("opensearch timeout")
            InMemoryLogStore.write_log(self, log_id, log)

    store = FailFirstStore()
    barrier = threading.Barrier(20)

    def send(_):
        barrier.wait()
        try:
            return handle_ingest(store, idem, make_log(), "k-fail-concurrent")
        except StorageError:
            return "storage_error"

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(send, range(20)))
    errors = [r for r in results if r == "storage_error"]
    ok = [r for r in results if r != "storage_error"]
    assert len(errors) == 1 and store.writes == 2
    assert {r.status for r in ok} == {202} and len({r.body["log_id"] for r in ok}) == 1
    assert len(store._logs) == 1


# ---------------------------------------------------------------- restart / storage layer
def test_tc14_restart_loses_cache_but_log_id_is_deterministic(store, clock):
    """Mo phong restart process (cache idempotency mat): cung key + payload -> cung log_id
    -> InMemory/OpenSearch ghi de cung _id, khong sinh ban ghi thu 2."""
    a = handle_ingest(store, IdempotencyStore(ttl_seconds=60, clock=clock), make_log(), "k-restart")
    b = handle_ingest(store, IdempotencyStore(ttl_seconds=60, clock=clock), make_log(), "k-restart")
    assert a.body["log_id"] == b.body["log_id"]
    assert len(store._logs) == 1


def test_tc15_opensearch_receives_same_document_id_on_retry(clock):
    """Lop storage that (OpenSearch, client gia - khong mang): 2 lan gui sau restart
    dung cung _id -> OpenSearch index() la upsert, khong tao document trung."""

    class FakeIndices:
        def exists(self, index):
            return True

    class FakeClient:
        def __init__(self):
            self.indices = FakeIndices()
            self.ids = []

        def index(self, index, id, body, **kw):
            self.ids.append((index, id))

    client = FakeClient()
    os_store = OpenSearchLogStore(client, log_index="logs")
    for _ in range(2):
        handle_ingest(os_store, IdempotencyStore(ttl_seconds=60, clock=clock), make_log(), "k-os")
    assert len(client.ids) == 2 and client.ids[0] == client.ids[1]
    assert client.ids[0][0] == "logs-2026.11.10"


def test_expired_records_are_purged_to_bound_memory(store, idem, clock):
    """NFR bo nho: ban ghi het han bi don, khong tang vo han."""
    for i in range(20):
        handle_ingest(store, idem, make_log(trace_id=f"t{i}"), f"k-{i}")
    assert len(idem) == 20
    clock.now += 61
    handle_ingest(store, idem, make_log(), "k-new")
    assert len(idem) == 1


def test_timestamp_is_not_now_dependent():
    """Guard flaky: du lieu test dung timestamp co dinh, khong doc dong ho he thong."""
    assert make_log()["timestamp"] == FIXED_TS
    assert datetime.fromisoformat(FIXED_TS.replace("Z", "+00:00")).tzinfo == timezone.utc


# ---------------------------------------------------------------- bo sung tu phan tich coverage
def test_tc01b_batch_without_key_keeps_legacy_behavior(store, idem):
    """K0 x E=/ingest/batch (coverage chi ra chua test): khong header -> UUID moi."""
    a = handle_ingest_batch(store, idem, [make_log()], None, 500)
    b = handle_ingest_batch(store, idem, [make_log()], None, 500)
    assert a.body["log_ids"] != b.body["log_ids"] and len(store._logs) == 2


def test_ttl_must_be_positive():
    with pytest.raises(ValueError):
        IdempotencyStore(ttl_seconds=0)


def test_get_treats_expired_record_as_absent(clock):
    """Nhanh het han ben trong get() (phong thu khi chua kip purge)."""
    s = IdempotencyStore(ttl_seconds=10, clock=clock)
    s.save("k", "fp", 202, {"accepted": True})
    assert s.get("k").status == 202
    clock.now += 10
    assert s.get("k") is None and len(s) == 0
