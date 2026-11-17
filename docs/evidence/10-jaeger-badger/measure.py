"""Same fixed workload and Docker stats schedule for memory and Badger."""
import argparse
import datetime as dt
import json
import pathlib
import re
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("phase", choices=["memory", "badger"])
p.add_argument("--container", default="lae107-jaeger-1")
p.add_argument("--base-url", default="http://127.0.0.1:18001")
p.add_argument("--output", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent)
args = p.parse_args()
out = args.output
out.mkdir(parents=True, exist_ok=True)
stop = threading.Event()
samples = []
started = time.monotonic()
(out / f"requests-{args.phase}.jsonl").write_text("", encoding="utf-8")

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sample():
    with (out / f"stats-{args.phase}.jsonl").open("w", encoding="utf-8") as f:
        while not stop.is_set():
            r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}",
                                args.container], capture_output=True, text=True)
            entry = {"utc": now(), "elapsed_seconds": round(time.monotonic() - started, 3)}
            if r.returncode:
                entry["error"] = r.stderr.strip()
            else:
                entry["stats"] = json.loads(r.stdout)
            samples.append(entry)
            f.write(json.dumps(entry) + "\n")
            f.flush()
            stop.wait(10)

thread = threading.Thread(target=sample, daemon=True)
thread.start()
counts = {}
network_errors = []
unexpected = []
print(f"{args.phase}: 60 warm-up + 600 measured requests at 1/s, then 60s idle", flush=True)
for i in range(660):
    url = args.base_url.rstrip("/") + "/api/items"
    expected = 200
    if i % 10 == 0:
        url += "?fault=runtime&rate=1&seed=107"
        expected = 500
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:
        status = "network_error"
        network_errors.append({"request": i, "error": str(e)})
    key = f"{status} (expected {expected})"
    counts[key] = counts.get(key, 0) + 1
    with (out / f"requests-{args.phase}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"utc": now(), "request": i, "status": status, "expected": expected}) + "\n")
    if status != expected:
        unexpected.append(i)
    if (i + 1) % 120 == 0:
        print(f"{args.phase}: {i + 1}/660 requests", flush=True)
    time.sleep(max(0, started + i + 1 - time.monotonic()))
time.sleep(60)
stop.set()
thread.join(timeout=10)
def mem_bytes(sample):
    size, unit = re.fullmatch(r"([\d.]+)\s*(B|KiB|MiB|GiB)", sample["stats"]["MemUsage"].split(" / ")[0]).groups()
    return float(size) * {"B": 1, "KiB": 1024, "MiB": 1024**2,
                          "GiB": 1024**3}[unit]
valid = [s for s in samples if "stats" in s]
steady = [mem_bytes(s) for s in valid if s["elapsed_seconds"] >= 660]
result = {"storage": args.phase, "completed_at_utc": now(), "elapsed_seconds": time.monotonic() - started,
          "warmup_requests": 60, "measured_requests": 600, "target_rps": 1,
          "concurrency": 1, "idle_seconds": 60, "status_counts_including_warmup": counts,
          "network_errors": network_errors, "sample_count": len(samples),
          "unexpected_status_requests": unexpected,
          "sample_errors": [s for s in samples if "error" in s],
          "peak_memory_bytes": max(map(mem_bytes, valid)) if valid else None,
          "idle_median_memory_bytes": statistics.median(steady) if steady else None}
(out / f"workload-{args.phase}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2), flush=True)
