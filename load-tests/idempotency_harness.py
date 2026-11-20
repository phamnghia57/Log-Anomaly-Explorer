"""VT-014 - harness tai 150 tac vu dong thoi cho ingest idempotent (muc tieu p95 <= 4.0 s).

Dung khi KHONG dung duoc stack that (Docker/OpenSearch/FastAPI). Kien truc:

  [process client: 150 thread, HTTP/1.1 keep-alive]  --HTTP-->  [process server rieng]
        do latency tung request + tung tac vu                    ThreadingHTTPServer (stdlib)
                                                                 -> ingest_core.handle_ingest*
                                                                    (CUNG code FastAPI goi)
                                                                 -> InMemoryLogStore + do tre
                                                                    gia lap OpenSearch

Do tre ghi gia lap: lognormal, median 11 ms, p95 ~ 27 ms - hieu chinh theo so do that cua nhom
(load-tests/ket-qua-load-test_stats.csv: POST /ingest median 11 ms, p95 31-34 ms). Bulk:
8 ms + 0.4 ms/log. Seed co dinh -> tai lap.

    python load-tests/idempotency_harness.py                 # 4 kich ban, in bang + JSON
    python load-tests/idempotency_harness.py --tasks 20 --users 150 --out ket-qua.json

Gioi han: khong co OpenSearch/uvicorn/rate limiter that; chi kiem chung chi phi cua lop
idempotency + khoa theo key duoi 150 ket noi dong thoi. Xem README_VT014.md.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET_P95_S = 4.0
LOG = {"timestamp": "2026-11-10T08:00:00Z", "level": "ERROR", "service": "demo-web",
       "trace_id": "t", "span_id": "s", "message": "Simulated failure in checkout"}


# =============================================================================== server
def serve(seed: int) -> None:
    sys.path.insert(0, str(REPO))
    from ingestion.src.idempotency import IdempotencyStore
    from ingestion.src.ingest_core import handle_ingest, handle_ingest_batch
    from ingestion.src.storage import InMemoryLogStore, StorageError

    class SimulatedOpenSearchStore(InMemoryLogStore):
        def __init__(self) -> None:
            super().__init__()
            self._rng = random.Random(seed)
            self._rng_lock = threading.Lock()
            self._write_lock = threading.Lock()
            self.write_calls = 0

        def _delay(self) -> float:
            with self._rng_lock:
                return self._rng.lognormvariate(math.log(0.011), 0.55)

        def write_log(self, log_id, log):
            time.sleep(self._delay())
            with self._write_lock:
                self.write_calls += 1
                self._logs[log_id] = log

        def write_logs_batch(self, items):
            time.sleep(0.008 + 0.0004 * len(items))
            with self._write_lock:
                self.write_calls += len(items)
                for log_id, log in items:
                    self._logs[log_id] = log

    state = {"store": SimulatedOpenSearchStore(), "idem": IdempotencyStore(86400)}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # im lang
            pass

        def _send(self, status: int, body: dict, headers: dict | None = None) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/_stats":
                s = state["store"]
                return self._send(200, {"docs": len(s._logs), "write_calls": s.write_calls,
                                        "quarantine": len(s._quarantine),
                                        "idem_records": len(state["idem"])})
            if self.path == "/_reset":
                state["store"], state["idem"] = SimulatedOpenSearchStore(), IdempotencyStore(86400)
                return self._send(200, {"reset": True})
            self._send(404, {})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            key = self.headers.get("Idempotency-Key")
            try:
                if self.path == "/ingest":
                    r = handle_ingest(state["store"], state["idem"], payload, key)
                elif self.path == "/ingest/batch":
                    r = handle_ingest_batch(state["store"], state["idem"], payload, key, 500)
                else:
                    return self._send(404, {})
            except StorageError:
                return self._send(503, {"accepted": False, "reason": "storage_unavailable"})
            self._send(r.status, r.body, r.headers)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 1024  # mac dinh 5 -> reset ket noi khi 150 client vao cung luc

    httpd = Server(("127.0.0.1", 0), Handler)
    print(httpd.server_address[1], flush=True)
    httpd.serve_forever()


# =============================================================================== client
class Client:
    def __init__(self, port: int) -> None:
        self.port = port
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)

    def call(self, method: str, path: str, body=None, key: str | None = None):
        headers = {"Content-Type": "application/json"}
        if key is not None:
            headers["Idempotency-Key"] = key
        data = json.dumps(body).encode() if body is not None else None
        start = time.perf_counter()
        try:
            self.conn.request(method, path, body=data, headers=headers)
            resp = self.conn.getresponse()
            raw = resp.read()
        except (ConnectionError, http.client.HTTPException, OSError):
            self.conn.close()
            self.conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            return time.perf_counter() - start, 0, {}, {}
        return (time.perf_counter() - start, resp.status,
                json.loads(raw) if raw else {}, dict(resp.getheaders()))


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(p / 100 * len(ordered)) - 1))]


def run_scenario(port: int, name: str, users: int, tasks: int, kind: str) -> dict:
    Client(port).call("GET", "/_reset")
    barrier = threading.Barrier(users)
    req_lat: list[float] = []
    task_lat: list[float] = []
    errors: list[str] = []
    mismatch = [0]
    lock = threading.Lock()

    def worker(uid: int) -> None:
        c = Client(port)
        local_req, local_task, local_err, local_mis = [], [], [], 0
        barrier.wait()
        for t in range(tasks):
            t0 = time.perf_counter()
            if kind == "unique_key":      # 1 lan gui + 2 lan gui lai cung key (retry)
                payload, key, repeats, path = dict(LOG, trace_id=f"u{uid}-t{t}"), f"u{uid}-t{t}", 3, "/ingest"
            elif kind == "hot_key":       # 150 user gui CUNG key + payload (tranh chap toi da)
                payload, key, repeats, path = LOG, "hot-key-0001", 1, "/ingest"
            elif kind == "no_key":        # baseline cu, khong idempotency
                payload, key, repeats, path = dict(LOG, trace_id=f"u{uid}-t{t}"), None, 1, "/ingest"
            else:                         # batch 50 log, gui 2 lan
                payload = [dict(LOG, trace_id=f"b{uid}-{t}-{i}") for i in range(50)]
                key, repeats, path = f"b{uid}-t{t}", 2, "/ingest/batch"
            first_ids = None
            for _ in range(repeats):
                dt, status, body, _ = c.call("POST", path, payload, key)
                local_req.append(dt)
                if status != 202:
                    local_err.append(str(status))
                    continue
                ids = body.get("log_id") or body.get("log_ids")
                if first_ids is None:
                    first_ids = ids
                elif ids != first_ids:
                    local_mis += 1
            local_task.append(time.perf_counter() - t0)
        with lock:
            req_lat.extend(local_req)
            task_lat.extend(local_task)
            errors.extend(local_err)
            mismatch[0] += local_mis

    start = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(users)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    wall = time.perf_counter() - start
    stats = Client(port).call("GET", "/_stats")[2]
    expected_docs = {"unique_key": users * tasks, "hot_key": 1, "no_key": users * tasks,
                     "batch": users * tasks * 50}[kind]
    return {
        "scenario": name, "users": users, "tasks_per_user": tasks, "requests": len(req_lat),
        "errors": len(errors), "error_rate": len(errors) / max(1, len(req_lat)),
        "replay_log_id_mismatch": mismatch[0],
        "req_p50_s": statistics.median(req_lat), "req_p95_s": pct(req_lat, 95),
        "req_p99_s": pct(req_lat, 99), "req_max_s": max(req_lat),
        "task_p95_s": pct(task_lat, 95), "throughput_rps": len(req_lat) / wall, "wall_s": wall,
        "docs": stats["docs"], "expected_docs": expected_docs,
        "no_duplicate": stats["docs"] == expected_docs,
        "pass_p95": pct(req_lat, 95) <= TARGET_P95_S and pct(task_lat, 95) <= TARGET_P95_S,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--users", type=int, default=150)
    ap.add_argument("--tasks", type=int, default=20)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.serve:
        serve(args.seed)
        return 0

    server = subprocess.Popen([sys.executable, "-I", __file__, "--serve", "--seed", str(args.seed)],
                              stdout=subprocess.PIPE, text=True)
    try:
        port = int(server.stdout.readline())
        results = [
            run_scenario(port, "S1 unique key + 2 retry", args.users, args.tasks, "unique_key"),
            run_scenario(port, "S2 hot key (cung key)", args.users, args.tasks, "hot_key"),
            run_scenario(port, "S3 baseline khong key", args.users, args.tasks, "no_key"),
            run_scenario(port, "S4 batch 50 log + 1 retry", args.users, max(1, args.tasks // 4), "batch"),
        ]
    finally:
        server.terminate()
    env = {"python": platform.python_version(), "cpu": os.cpu_count(), "platform": platform.platform(),
           "seed": args.seed, "target_p95_s": TARGET_P95_S}
    print(f"Moi truong: {env}")
    print(f"{'Kich ban':28s} {'req':>6s} {'loi':>4s} {'p50':>7s} {'p95':>7s} {'p99':>7s} "
          f"{'max':>7s} {'task p95':>8s} {'rps':>7s} {'docs/ky vong':>14s}  ket luan")
    for r in results:
        print(f"{r['scenario']:28s} {r['requests']:6d} {r['errors']:4d} {r['req_p50_s']*1000:6.0f}ms "
              f"{r['req_p95_s']*1000:6.0f}ms {r['req_p99_s']*1000:6.0f}ms {r['req_max_s']*1000:6.0f}ms "
              f"{r['task_p95_s']*1000:7.0f}ms {r['throughput_rps']:7.0f} "
              f"{str(r['docs']) + '/' + str(r['expected_docs']):>14s}  "
              f"{'PASS' if r['pass_p95'] and r['no_duplicate'] and not r['errors'] and not r['replay_log_id_mismatch'] else 'FAIL'}")
    if args.out:
        Path(args.out).write_text(json.dumps({"env": env, "results": results}, indent=2), encoding="utf-8")
    ok = all(r["pass_p95"] and r["no_duplicate"] and not r["errors"] for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
