"""VT-014 - kiem tra nguy co flaky cua bo test idempotency.

    cd ingestion && python tests/tools/flaky_check.py [--orders 10] [--repeat 200]

1. ORDER / SHARED STATE: chay toan bo test theo thu tu dao nguoc + N thu tu ngau nhien
   (seed in ra de tai lap). Test phu thuoc thu tu se fail o mot hoan vi nao do.
2. CONCURRENCY: lap lai cac test dong thoi (TC-13, TC-13b) nhieu lan, dem so lan fail.
3. NETWORK: chay suite voi socket bi chan -> chung minh test khong goi mang.
4. TIME: chay suite voi cac mui gio TZ khac nhau (dong ho gia + timestamp co dinh).
"""

from __future__ import annotations

import argparse
import os
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
INGESTION = HERE.parents[2]
TEST_FILES = ["tests/test_ingest_core.py", "tests/test_idempotency.py"]


def pytest_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args]


def collect() -> list[str]:
    out = subprocess.run(pytest_cmd("--collect-only", *TEST_FILES), cwd=INGESTION,
                         capture_output=True, text=True).stdout
    return [ln.strip() for ln in out.splitlines() if "::" in ln]


def run_ids(ids: list[str], env: dict | None = None) -> tuple[int, str]:
    proc = subprocess.run(pytest_cmd(*ids), cwd=INGESTION, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-200:]
    return proc.returncode, tail


def check_order(n_orders: int) -> bool:
    ids = collect()
    print(f"[order] {len(ids)} test id")
    if not ids:
        print("[order] khong collect duoc test")
        return False
    ok = True
    plans = [("reversed", list(reversed(ids)))]
    for seed in range(1, n_orders + 1):
        shuffled = ids[:]
        random.Random(seed).shuffle(shuffled)
        plans.append((f"seed={seed}", shuffled))
    for name, order in plans:
        rc, tail = run_ids(order)
        ok &= rc == 0
        print(f"[order] {name:10s} rc={rc}  {tail}  (first={order[0].split('::')[-1]})")
    return ok


def check_concurrency(repeat: int) -> bool:
    sys.path.insert(0, str(INGESTION.parent))
    sys.path.insert(0, str(INGESTION / "tests"))
    import test_idempotency as t  # noqa: E402
    from ingestion.src.idempotency import IdempotencyStore  # noqa: E402

    ok = True
    for fn in (t.test_tc13_150_concurrent_identical_requests_write_once,
               t.test_tc13b_first_concurrent_request_fails_waiters_are_not_stuck):
        fails, start = 0, time.perf_counter()
        for _ in range(repeat):
            try:
                fn(IdempotencyStore(ttl_seconds=60, clock=t.FakeClock()))
            except AssertionError:
                fails += 1
        ok &= fails == 0
        print(f"[concurrency] {fn.__name__}: {repeat} lan, fail={fails}, "
              f"{time.perf_counter() - start:.1f}s")
    return ok


def check_network() -> bool:
    import pytest

    def blocked(*a, **k):
        raise RuntimeError("NETWORK BLOCKED by flaky_check")

    original = socket.socket.connect
    socket.socket.connect = blocked  # type: ignore[assignment]
    try:
        os.chdir(INGESTION)
        rc = pytest.main(["-q", "-p", "no:cacheprovider", *TEST_FILES])
    finally:
        socket.socket.connect = original  # type: ignore[assignment]
    print(f"[network] socket.connect bi chan -> pytest rc={int(rc)}")
    return int(rc) == 0


def check_timezones() -> bool:
    ok = True
    for tz in ("UTC", "Asia/Ho_Chi_Minh", "Pacific/Kiritimati", "America/Adak"):
        rc, tail = run_ids(TEST_FILES, env={"TZ": tz})
        ok &= rc == 0
        print(f"[time] TZ={tz:20s} rc={rc}  {tail}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", type=int, default=10)
    ap.add_argument("--repeat", type=int, default=200)
    args = ap.parse_args()
    results = {
        "order": check_order(args.orders),
        "time": check_timezones(),
        "concurrency": check_concurrency(args.repeat),
        "network": check_network(),
    }
    print("\nKET QUA:", ", ".join(f"{k}={'OK' if v else 'FLAKY'}" for k, v in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
