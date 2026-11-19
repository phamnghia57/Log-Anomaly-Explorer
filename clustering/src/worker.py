"""Run from repository root: python -m clustering.src.worker [--once] [--window-to ISO8601]."""
import argparse
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from .alert import check_and_alert_batch, get_threshold
from .anomaly_score import _parse_ts
from .pipeline import analyze
from .storage import OpenSearchStore, StorageError
from .incidents import IncidentRepository
from .ml_augment import TfidfAugmenter
from .healthcheck import ping

HISTORY_RETENTION_INTERVAL_SECONDS = 3600


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--window-to", help="Exclusive end; implies a single run")
    args = parser.parse_args()
    seconds = int(os.getenv("WINDOW_SECONDS", "60"))
    history = int(os.getenv("HISTORY_WINDOWS", "30"))
    lag = int(os.getenv("INGESTION_LAG_SECONDS", "10"))
    retention_days = int(os.getenv("RETENTION_DAYS", "30"))
    if seconds <= 0 or history < 1 or lag < 0 or retention_days < 1:
        parser.error("WINDOW_SECONDS > 0, HISTORY_WINDOWS >= 1, INGESTION_LAG_SECONDS >= 0 and RETENTION_DAYS >= 1 required")
    logging.basicConfig(level=logging.INFO)
    augmenter = None
    if os.getenv("ML_AUGMENT_ENABLED", "true").lower() in {"true", "1", "yes"}:
        augmenter = TfidfAugmenter(
            os.getenv("ML_STATE_PATH", "clustering/data/ml_templates.json"),
            threshold=float(os.getenv("ML_SIMILARITY_THRESHOLD", "0.9")),
            margin=float(os.getenv("ML_SIMILARITY_MARGIN", "0.05")),
            max_templates=int(os.getenv("ML_MAX_TEMPLATES", "2000")),
        )
    store = OpenSearchStore()
    try:
        store.ensure_ready()
        incidents = IncidentRepository(store)
        delivery_failed = False
        next_retention = 0.0

        def report_delivery(success):
            nonlocal delivery_failed
            delivery_failed = not success
            if not success and args.window_to is None:
                ping(failed=True)

        while True:
            cycle_start = time.perf_counter()
            delivery_failed = False
            now = datetime.now(timezone.utc).timestamp() - lag
            end = _parse_ts(args.window_to) if args.window_to else datetime.fromtimestamp(
                (now // seconds) * seconds, timezone.utc)
            start = end - timedelta(seconds=seconds * (history + 1))
            logs = list(store.read_logs(start.isoformat(), end.isoformat()))
            records = analyze(logs, end.isoformat(), window_seconds=seconds,
                              history_windows=history, threshold=get_threshold(), augmenter=augmenter)
            check_and_alert_batch(records, window_to=end.isoformat(), store=store, incidents=incidents,
                                  on_delivery=report_delivery)
            for _, record in records:
                store.write_cluster(record)
                store.write_history(record, end.isoformat())
            cycle_seconds = time.perf_counter() - cycle_start
            if args.window_to is None:
                store.write_heartbeat(datetime.now(timezone.utc).isoformat(), cycle_seconds=cycle_seconds,
                                      logs_read=len(logs), clusters_out=len(records), window_to=end.isoformat())
                if not delivery_failed:
                    ping()
            logging.info("Processed %s: cycle_seconds=%.3f logs_read=%d clusters_out=%d",
                         end.isoformat(), cycle_seconds, len(logs), len(records))
            if args.window_to is None and time.monotonic() >= next_retention:
                next_retention = time.monotonic() + HISTORY_RETENTION_INTERVAL_SECONDS
                cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
                try:
                    deleted = store.delete_history_before(cutoff)
                    logging.info("Cluster history retention: deleted=%d cutoff=%s", deleted, cutoff)
                except StorageError:
                    logging.exception("Cluster history retention failed; will retry on the next scheduled run")
            if args.once or args.window_to:
                break
            time.sleep(max(1, end.timestamp() + seconds + lag - time.time()))
    finally:
        store.close()


if __name__ == "__main__":
    main()
