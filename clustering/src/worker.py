"""Run from repository root: python -m clustering.src.worker [--once] [--window-to ISO8601]."""
import argparse
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from .alert import check_and_alert, get_threshold
from .anomaly_score import _parse_ts
from .pipeline import analyze
from .storage import OpenSearchStore
from .ml_augment import TfidfAugmenter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--window-to", help="Exclusive end; implies a single run")
    args = parser.parse_args()
    seconds = int(os.getenv("WINDOW_SECONDS", "60"))
    history = int(os.getenv("HISTORY_WINDOWS", "30"))
    lag = int(os.getenv("INGESTION_LAG_SECONDS", "10"))
    if seconds <= 0 or history < 1 or lag < 0:
        parser.error("WINDOW_SECONDS > 0, HISTORY_WINDOWS >= 1, INGESTION_LAG_SECONDS >= 0 required")
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
        while True:
            now = datetime.now(timezone.utc).timestamp() - lag
            end = _parse_ts(args.window_to) if args.window_to else datetime.fromtimestamp(
                (now // seconds) * seconds, timezone.utc)
            start = end - timedelta(seconds=seconds * (history + 1))
            logs = list(store.read_logs(start.isoformat(), end.isoformat()))
            records = analyze(logs, end.isoformat(), window_seconds=seconds,
                              history_windows=history, threshold=get_threshold(), augmenter=augmenter)
            for service, record in records:
                store.write_cluster(record)
                check_and_alert(record, service)
                store.write_cluster(record)
            logging.info("Processed %s: %d clusters", end.isoformat(), len(records))
            if args.once or args.window_to:
                break
            time.sleep(max(1, end.timestamp() + seconds + lag - time.time()))
    finally:
        store.close()


if __name__ == "__main__":
    main()
