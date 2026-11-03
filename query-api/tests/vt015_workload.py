"""Reproducible SIMULATED backend workload over HTTP to one API subprocess.

Run from repository root:
  .venv-vt015/Scripts/python.exe query-api/tests/vt015_workload.py
No production endpoint or data is used. SQLite files are temporary and isolated.
"""
import argparse
import csv
import importlib
import json
import math
import os
import platform
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vt015_sqlite_simulator import SQLiteApprovalClient


def serve(args):
    import uvicorn
    os.environ["STORAGE_BACKEND"] = "memory"
    main = importlib.import_module("query-api.src.main")
    repository_class = importlib.import_module("query-api.src.approvals").ApprovalRepository
    repository = repository_class(SimpleNamespace(client=SQLiteApprovalClient(args.db, args.index)))
    repository.index = args.index

    class IsolatedClusters:
        def get_cluster(self, cluster_id):
            permitted = {"same-2", "same-80"} | {f"independent-{i}" for i in range(80)}
            return {"cluster_id": cluster_id} if cluster_id in permitted else None

    main.cluster_store = IsolatedClusters()
    main.app.state.approval_repository = repository
    uvicorn.run(main.app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def run(args):
    import httpx
    import jwt
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    index = "vt015-sim-" + uuid.uuid4().hex
    secret = secrets.token_urlsafe(48)
    env = dict(os.environ, STORAGE_BACKEND="memory", JWT_SECRET=secret)
    token = jwt.encode({"sub": "workload-reviewer", "role": "reviewer",
                        "exp": int(time.time()) + 3600}, secret, algorithm="HS256")
    rows, scenarios = [], []
    with tempfile.TemporaryDirectory(prefix="vt015-sim-") as temporary:
        db = Path(temporary, "approvals.sqlite")
        storage = SQLiteApprovalClient(db, index)
        command = [sys.executable, str(Path(__file__).resolve()), "--serve", "--db", str(db),
                   "--port", str(port), "--index", index]
        with (out / "workload-server.txt").open("w", encoding="utf-8") as server_log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=server_log,
                                       stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60,
                                  trust_env=False, limits=httpx.Limits(
                                      max_connections=100, max_keepalive_connections=100)) as client:
                    deadline = time.monotonic() + 30
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError("API process stopped; inspect workload-server.txt")
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if time.monotonic() > deadline:
                            raise TimeoutError("API startup exceeded 30 seconds")
                        time.sleep(0.1)
                    for scenario, cluster_ids in [
                        ("same_cluster_2", ["same-2"] * 2),
                        ("same_cluster_80", ["same-80"] * 80),
                        ("independent_clusters_80", [f"independent-{i}" for i in range(80)]),
                    ]:
                        barrier = Barrier(len(cluster_ids))

                        def request(pair):
                            number, cluster_id = pair
                            barrier.wait(timeout=30)
                            start = time.perf_counter_ns()
                            status, error = 0, ""
                            try:
                                response = client.post(f"/clusters/{cluster_id}/approval",
                                                       headers={"Authorization": "Bearer " + token})
                                status = response.status_code
                                if status not in (201, 409):
                                    error = response.text
                            except httpx.HTTPError as exc:
                                error = type(exc).__name__ + ": " + str(exc)
                            elapsed = (time.perf_counter_ns() - start) / 1_000_000
                            return {"scenario": scenario, "request": number, "cluster_id": cluster_id,
                                    "status": status, "latency_ms": elapsed, "error": error}

                        with ThreadPoolExecutor(max_workers=len(cluster_ids)) as pool:
                            batch = list(pool.map(request, enumerate(cluster_ids)))
                        rows.extend(batch)
                        persisted = [d for d in storage.documents() if d["cluster_id"] in set(cluster_ids)]
                        successes = sum(r["status"] == 201 for r in batch)
                        conflicts = sum(r["status"] == 409 for r in batch)
                        expected = len(set(cluster_ids))
                        scenarios.append({"scenario": scenario, "concurrency": len(cluster_ids),
                                          "requests": len(batch), "successes": successes,
                                          "conflicts": conflicts,
                                          "errors": sum(bool(r["error"]) for r in batch),
                                          "persisted": len(persisted),
                                          "valid": successes == expected and
                                          conflicts == len(batch) - expected and
                                          len(persisted) == expected and
                                          all(d["approved_by"] == "workload-reviewer" for d in persisted)})
                    persisted_documents = storage.documents()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    with (out / "workload-raw.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metrics = []
    for scenario in [s["scenario"] for s in scenarios] + ["all"]:
        for status, label in [(201, "success"), (409, "conflict")]:
            values = [r["latency_ms"] for r in rows if r["status"] == status and
                      (scenario == "all" or r["scenario"] == scenario)]
            if values:
                metrics.append({"scenario": scenario, "response": label, "count": len(values),
                                "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95),
                                "p99_ms": percentile(values, .99), "max_ms": max(values),
                                "p95_below_2500_ms": percentile(values, .95) < 2500})
    metadata = {"backend": "SIMULATED SQLite unique-key inserts; production ApprovalRepository",
                "api_processes": 1, "http_transport": "loopback TCP HTTP; separate uvicorn process",
                "load_generator": "same machine, up to 80 threads and 100 pooled connections",
                "clock": "time.perf_counter_ns; includes HTTP/pool/server queueing; excludes barrier wait",
                "percentile_method": "nearest rank", "python": platform.python_version(),
                "platform": platform.platform(), "logical_cpus": os.cpu_count(),
                "sqlite_version": sqlite3.sqlite_version, "isolated_index": index,
                "total_requests": len(rows), "successes": sum(r["status"] == 201 for r in rows),
                "conflicts": sum(r["status"] == 409 for r in rows),
                "errors": sum(bool(r["error"]) for r in rows),
                "persisted_count": len(persisted_documents), "scenarios": scenarios, "metrics": metrics}
    (out / "workload-results.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (out / "workload-persisted.json").write_text(json.dumps(persisted_documents, indent=2), encoding="utf-8")
    lines = ["# VT-015 simulated HTTP workload", "", "**SIMULATED backend; not production performance.**",
             "", "One API subprocess; loopback HTTP; 80 client threads for each 80-request scenario.",
             "SQLite unique-key transactions exercise the actual ApprovalRepository. Cluster reads are",
             "an isolated in-memory fixture. No OpenSearch transport/sharding/replication is modeled.",
             "Hardware is recorded in hardware.txt. Temporary database was removed after validation.",
             "", f"Requests: {len(rows)}; successes: {metadata['successes']}; conflicts: {metadata['conflicts']}; errors: {metadata['errors']}.",
             "", "| Scenario | Requests / concurrency | 201 | 409 | Persisted | Valid |",
             "|---|---:|---:|---:|---:|---|"]
    for s in scenarios:
        lines.append(f"| {s['scenario']} | {s['requests']} / {s['concurrency']} | {s['successes']} | {s['conflicts']} | {s['persisted']} | {s['valid']} |")
    lines += ["", "Nearest-rank percentiles in milliseconds, separated by response status.",
              "Monotonic perf_counter_ns spans client send to full response receipt, including queueing.",
              "Barrier waiting and API startup are excluded. No approval warm-up requests were sent.",
              "", "| Scenario | Response | n | p50 | p95 | p99 | Max | p95 < 2500 ms |",
              "|---|---|---:|---:|---:|---:|---:|---|"]
    for m in metrics:
        lines.append(f"| {m['scenario']} | {m['response']} | {m['count']} | {m['p50_ms']:.3f} | {m['p95_ms']:.3f} | {m['p99_ms']:.3f} | {m['max_ms']:.3f} | {m['p95_below_2500_ms']} |")
    lines += ["", "Only one batch per scenario; percentiles (especially n=1) have limited statistical strength.",
              "Compare the 80-task rows to the 2.5-second threshold; aggregate mixes scenarios.",
              "These values do not establish a production SLO or OpenSearch concurrency correctness.",
              "Reproduce: `.venv-vt015/Scripts/python.exe query-api/tests/vt015_workload.py`."]
    (out / "workload-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    if not all(s["valid"] for s in scenarios) or metadata["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--db")
    parser.add_argument("--port", type=int)
    parser.add_argument("--index")
    parser.add_argument("--output", default="docs/task/VT-015/evidence")
    arguments = parser.parse_args()
    serve(arguments) if arguments.serve else run(arguments)
