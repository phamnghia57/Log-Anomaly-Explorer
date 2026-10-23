"""Controlled live evaluation. Requires isolated demo/ingestion and OpenSearch."""
import json
import os
import time
import urllib.request
from urllib.error import HTTPError
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from clustering.src.pipeline import analyze
from clustering.src.ml_augment import TfidfAugmenter


def iso(value):
    return value.isoformat()


def read(url, body=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    demo = os.environ.get("EVAL_DEMO_URL", "http://pr-eval-demo:8001")
    search = "http://opensearch:9200"
    index = "pr-fresh-logs"
    read(demo + "/health")
    read("http://pr-eval-ingestion:8000/health")
    start = datetime.now(timezone.utc) + timedelta(seconds=2)
    run = start.strftime("%Y%m%dT%H%M%SZ")
    out = Path("clustering/evaluation/runs") / run
    out.mkdir(parents=True, exist_ok=False)
    faults = {
        "value": (422, "Simulated validation failure: required item data is invalid"),
        "connection": (502, "Simulated connection failure: downstream dependency unreachable"),
        "runtime": (500, "Simulated runtime failure"),
        "timeout": (504, "Simulated downstream timeout"),
        "downstream": (500, "Simulated downstream failure"),
    }
    labels = []
    requests = []
    for window, repeats in enumerate((1, 1, 6, 1)):
        window_start = start + timedelta(seconds=30 * window)
        window_end = window_start + timedelta(seconds=30)
        while datetime.now(timezone.utc) < window_start:
            time.sleep(0.2)
        for platform in ("web", "mobile-api"):
            for fault, (expected, signature) in faults.items():
                if window == 2:
                    labels.append({"incident_id": f"{run}-{platform}-{fault}",
                                   "service": "demo-" + platform,
                                   "window_from": iso(window_start), "window_to": iso(window_end),
                                   "expected_cluster_signature": signature})
                for _ in range(repeats):
                    url = f"{demo}/simulate-error?platform={platform}&fault={fault}&rate=1&seed=1"
                    try:
                        read(url)
                        raise RuntimeError("Expected injected HTTP error")
                    except HTTPError as error:
                        if error.code != expected:
                            raise
                    requests.append({"window": window, "platform": platform,
                                     "fault": fault, "http_status": expected})
        if datetime.now(timezone.utc) >= window_end:
            raise RuntimeError("Requests exceeded their assigned window")
        print(f"window={window} repeats={repeats} completed", flush=True)
    end = start + timedelta(seconds=120)
    while datetime.now(timezone.utc) < end:
        time.sleep(0.2)
    read(search + f"/{index}/_refresh", {})
    response = read(search + f"/{index}/_search", {"size": 1000,
        "query": {"range": {"timestamp": {"gte": iso(start), "lt": iso(end)}}}})
    hits = response["hits"]["hits"]
    if response.get("timed_out") or response["_shards"]["failed"] or response["hits"]["total"]["value"] != len(hits):
        raise RuntimeError("Incomplete log export")
    logs = [{**hit["_source"], "log_id": hit["_id"]} for hit in hits]
    if len(logs) != len(requests):
        raise RuntimeError(f"Ingestion lost logs: {len(logs)}/{len(requests)}")
    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    save("logs.json", logs)
    save("labels.json", {"source": "Known live fault injection parameters; pending team review", "incidents": labels})
    save("requests.json", requests)
    for mode in ("rule", "ml"):
        with TemporaryDirectory() as temp:
            augmenter = TfidfAugmenter(Path(temp) / "state.json") if mode == "ml" else None
            predictions = []
            for window in (2, 3):
                predictions.extend(record for _, record in analyze(
                    logs, iso(start + timedelta(seconds=30 * (window + 1))),
                    window_seconds=30, history_windows=2, threshold=2.0, augmenter=augmenter))
            save(f"predictions-{mode}.json", predictions)
            if augmenter:
                save("ml-state.json", json.loads(augmenter.state_path.read_text(encoding="utf-8")))
    save("config.json", {"start": iso(start), "end": iso(end), "logs": len(logs),
         "window_seconds": 30, "history_windows": 2, "threshold": 2.0,
         "source_index": index, "baseline_per_cluster": 1, "burst_per_cluster": 6,
         "recovery_per_cluster": 1, "ml_threshold": 0.9, "ml_margin": 0.05})
    print(str(out), flush=True)


if __name__ == "__main__":
    main()
