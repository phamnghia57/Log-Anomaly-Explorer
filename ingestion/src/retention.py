"""
Retention job - xoa log qua han.

So ngay luu lay tu bien moi truong RETENTION_DAYS (khong hardcode).

Hai cach chay dinh ky:
  1. Tu dong trong service: main.py khoi dong vong lap nen, chu ky RETENTION_INTERVAL_SECONDS.
  2. Cron / scheduler ben ngoai:  python -m src.retention   (chay tu thu muc ingestion/)
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from . import config
from .storage import LogStore

logger = logging.getLogger("ingestion.retention")

DEFAULT_RETENTION_DAYS = config.RETENTION_DAYS


def run_retention(store: LogStore, retention_days: int | None = None) -> int:
    """Xoa moi log cu hon `retention_days` ngay. Tra ve so log da xoa."""
    days = DEFAULT_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return store.delete_older_than(cutoff.isoformat())


def start_scheduler(store: LogStore, interval_seconds: int | None = None) -> threading.Event | None:
    """Chay run_retention dinh ky trong thread nen. Tra ve Event de dung (stop.set()).
    interval <= 0 -> khong chay (dung cron ben ngoai)."""
    interval = config.RETENTION_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
    if interval <= 0:
        return None
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            try:
                deleted = run_retention(store)
                logger.info("retention: deleted %d logs older than %d days", deleted, DEFAULT_RETENTION_DAYS)
            except Exception:  # noqa: BLE001 - job nen khong duoc chet vi loi tam thoi
                logger.exception("retention run failed")

    threading.Thread(target=loop, name="retention", daemon=True).start()
    return stop


if __name__ == "__main__":
    from .storage import build_store

    logging.basicConfig(level=logging.INFO)
    s = build_store()
    s.ensure_ready()
    print(f"deleted={run_retention(s)} retention_days={DEFAULT_RETENTION_DAYS}")
