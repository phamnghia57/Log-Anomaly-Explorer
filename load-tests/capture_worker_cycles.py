"""Poll the worker's latest heartbeat into CSV; run from repository root."""
import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

from clustering.src.storage import OpenSearchStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=360)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--rate", type=int, choices=(10, 50, 100), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds <= 0 or args.interval <= 0:
        parser.error("seconds and interval must be positive")
    store = OpenSearchStore()
    deadline = time.monotonic() + args.seconds
    last = None
    try:
        with args.output.open("x", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=("target_errors_per_second", "observed_at", "last_processed_at", "window_to",
                                                     "cycle_seconds", "logs_read", "clusters_out"))
            writer.writeheader()
            while time.monotonic() < deadline:
                result = store.client.get(index=store.heartbeat, id="worker", ignore=[404])
                source = result.get("_source", {}) if result.get("found") else {}
                stamp = source.get("last_processed_at")
                if stamp and stamp != last:
                    writer.writerow({"target_errors_per_second": args.rate,
                                     "observed_at": datetime.now(timezone.utc).isoformat(),
                                     **{key: source.get(key) for key in
                                        ("last_processed_at", "window_to", "cycle_seconds", "logs_read", "clusters_out")}})
                    out.flush()
                    last = stamp
                time.sleep(args.interval)
    finally:
        store.close()


if __name__ == "__main__":
    main()
