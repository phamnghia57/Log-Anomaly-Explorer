import argparse
import json
import time
from datetime import datetime, timedelta, timezone

import httpx

OS = "http://127.0.0.1:19200"
DEMO = "http://127.0.0.1:18001"
MARKERS = {"value": "simulated validation failure", "connection": "simulated connection failure",
           "timeout": "simulated downstream timeout", "runtime": "simulated runtime failure",
           "downstream": "simulated downstream failure"}


def now():
    return datetime.now(timezone.utc)


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def wait_until_second(sec):
    while True:
        current = now()
        if int(current.second) == sec and current.microsecond < 200_000:
            return
        time.sleep(0.05)


def heartbeat(prefix):
    r = httpx.get(f"{OS}/{prefix}-clusters-heartbeat/_doc/worker")
    return r.json().get("_source") if r.status_code == 200 else None


def trial(prefix, fault, platform, sec, k):
    wait_until_second(sec)
    path = "/api/items" if platform == "web" else "/api/mobile/items"
    service = "demo-web" if platform == "web" else "demo-mobile-api"
    marker = MARKERS[fault]
    t_first = now()
    with httpx.Client(timeout=5, trust_env=False) as client:
        codes = [client.get(DEMO + path, params={"fault": fault, "rate": 1}).status_code for _ in range(k)]
    t_last = now()
    query = {"size": 5, "query": {"bool": {"filter": [
        {"term": {"service": service}},
        {"prefix": {"signature": marker}},
        {"terms": {"status": ["anomalous", "alerted"]}},
        {"range": {"last_seen": {"gte": (t_first - timedelta(seconds=1)).isoformat()}}},
    ]}}}
    hit = None
    while hit is None and (now() - t_last).total_seconds() < 240:
        r = httpx.post(f"{OS}/{prefix}-clusters/_search", json=query)
        hits = r.json().get("hits", {}).get("hits", []) if r.status_code == 200 else []
        hit = next((h["_source"] for h in hits if marker in h["_source"]["signature"]), None)
        if hit is None:
            time.sleep(0.25)
    t_visible = now()
    window_to = t_last.replace(second=0, microsecond=0) + timedelta(minutes=1)
    hb = None
    for _ in range(240):
        hb = heartbeat(prefix)
        if hb and parse(hb["window_to"]) >= window_to:
            break
        time.sleep(0.5)
    out = {"fault": fault, "service": service, "fire_second": sec, "k": k, "codes": sorted(set(codes)),
           "fired_from": t_first.isoformat(), "fired_to": t_last.isoformat(),
           "visible_at": t_visible.isoformat(), "found": hit is not None}
    if hit:
        out.update({"cluster_id": hit["cluster_id"], "score": hit["score"], "status": hit["status"],
                    "log_count": len(hit["log_ids"]), "first_seen": hit["first_seen"], "last_seen": hit["last_seen"],
                    "latency_from_first_log_s": round((t_visible - parse(hit["first_seen"])).total_seconds(), 2),
                    "latency_from_last_log_s": round((t_visible - parse(hit["last_seen"])).total_seconds(), 2)})
    if hb:
        out.update({"hb_window_to": hb.get("window_to"), "hb_last_processed_at": hb.get("last_processed_at"),
                    "hb_cycle_seconds": round(hb.get("cycle_seconds", 0), 3), "hb_logs_read": hb.get("logs_read"),
                    "hb_clusters_out": hb.get("clusters_out")})
    print(json.dumps(out), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="e2e")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--trials", required=True, help="fault:platform:second,...")
    args = parser.parse_args()
    for spec in args.trials.split(","):
        fault, platform, sec = spec.split(":")
        trial(args.prefix, fault, platform, int(sec), args.k)


if __name__ == "__main__":
    main()
