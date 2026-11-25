import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from itertools import islice
from uuid import uuid4


def set_env(prefix):
    os.environ.setdefault("OPENSEARCH_URL", "http://127.0.0.1:19200")
    os.environ["STORAGE_BACKEND"] = "opensearch"
    os.environ["LOG_INDEX"] = f"{prefix}-logs"
    os.environ["CLUSTER_INDEX"] = f"{prefix}-clusters"
    os.environ["HISTORY_INDEX"] = f"{prefix}-cluster-history"
    os.environ["ALERT_WEBHOOK_URL"] = ""
    os.environ["HEALTHCHECK_PING_URL"] = ""
    os.environ["ANOMALY_THRESHOLD"] = "3.0"


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def cmd_seed(args):
    set_env(args.prefix)
    from ingestion.src.storage import build_store
    from clustering.evaluation.generate_timeline import generate_timeline

    store = build_store()
    store.ensure_ready()
    templates, _, _ = generate_timeline(seed=98)
    end = parse(args.end)
    total = args.rate * 60 * args.minutes
    start = end - timedelta(minutes=args.minutes)
    step = 1.0 / args.rate

    def payloads():
        for i in range(total):
            original = templates[i % len(templates)]
            ts = start + timedelta(seconds=i * step)
            yield {**original, "timestamp": ts.isoformat(), "trace_id": uuid4().hex, "span_id": uuid4().hex[:16]}

    it = payloads()
    t0 = time.perf_counter()
    sent = 0
    while batch := list(islice(it, 500)):
        store.write_logs_batch([(str(uuid4()), log) for log in batch])
        sent += len(batch)
    store.client.indices.refresh(index=store.read_indices, ignore_unavailable=True, allow_no_indices=True)
    print(json.dumps({"seeded": sent, "rate": args.rate, "minutes": args.minutes,
                      "from": start.isoformat(), "to": end.isoformat(),
                      "seconds": round(time.perf_counter() - t0, 2)}))


def cmd_cycle(args):
    set_env(args.prefix)
    import psutil
    from clustering.src import pipeline
    from clustering.src.alert import check_and_alert_batch, get_threshold
    from clustering.src.incidents import IncidentRepository
    from clustering.src.ml_augment import TfidfAugmenter
    from clustering.src.storage import OpenSearchStore

    proc = psutil.Process()
    if args.ml == "on":
        import sklearn.feature_extraction.text  # noqa: F401
    store = OpenSearchStore()
    store.ensure_ready()
    incidents = IncidentRepository(store)
    augmenter = None
    if args.ml == "on":
        augmenter = TfidfAugmenter(args.ml_state, threshold=0.9, margin=0.05, max_templates=2000)

    end = parse(args.end)
    start = end - timedelta(seconds=60 * 31)
    rss0 = proc.memory_info().rss
    c0 = time.perf_counter()
    logs = list(store.read_logs(start.isoformat(), end.isoformat()))
    c1 = time.perf_counter()
    rss_read = proc.memory_info().rss
    records = pipeline.analyze(logs, end.isoformat(), window_seconds=60, history_windows=30,
                               threshold=get_threshold(), augmenter=augmenter)
    c2 = time.perf_counter()
    check_and_alert_batch(records, window_to=end.isoformat(), store=store, incidents=incidents,
                          on_delivery=lambda ok: None)
    c3 = time.perf_counter()
    if args.writes == "loop":
        for _, record in records:
            store.write_cluster(record)
            store.write_history(record, end.isoformat())
    elif args.writes == "loop-norefresh":
        for _, record in records:
            store.client.index(index=store.clusters, id=record["cluster_id"], body=record)
            point = {name: record[name] for name in ("cluster_id", "score", "status")}
            point.update({name: record[name] for name in ("first_seen", "last_seen") if name in record})
            point["recorded_at"] = end.isoformat()
            store.client.index(index=store.history, body=point)
    else:
        store.write_cycle([record for _, record in records], end.isoformat())
    c4 = time.perf_counter()
    print(json.dumps({
        "prefix": args.prefix, "end": end.isoformat(), "ml": args.ml, "writes": args.writes,
        "logs_read": len(logs), "clusters_out": len(records),
        "read_s": round(c1 - c0, 3), "analyze_s": round(c2 - c1, 3), "alert_s": round(c3 - c2, 3),
        "writes_s": round(c4 - c3, 3), "cycle_s": round(c4 - c0, 3),
        "rss_start_mib": round(rss0 / 2**20, 1), "rss_after_read_mib": round(rss_read / 2**20, 1),
    }))
    store.close()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--prefix", required=True)
    s.add_argument("--rate", type=int, required=True)
    s.add_argument("--minutes", type=int, default=31)
    s.add_argument("--end", required=True)
    c = sub.add_parser("cycle")
    c.add_argument("--prefix", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--ml", choices=("on", "off"), default="on")
    c.add_argument("--writes", choices=("loop", "loop-norefresh", "cycle"), default="cycle")
    c.add_argument("--ml-state", default="")
    args = parser.parse_args()
    {"seed": cmd_seed, "cycle": cmd_cycle}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
