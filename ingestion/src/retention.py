"""
Retention job - drop daily index qua han (memory backend xoa log) va xoa ban
ghi quarantine qua han.

So ngay luu lay tu bien moi truong (khong hardcode):
  RETENTION_DAYS             log chinh (drop ca index logs-YYYY.MM.DD)
  QUARANTINE_RETENTION_DAYS  log sai schema (delete_by_query theo received_at),
                             mac dinh = RETENTION_DAYS

Hai cach chay dinh ky:
  1. Tu dong trong service: main.py khoi dong vong lap nen, chu ky RETENTION_INTERVAL_SECONDS.
  2. Cron / scheduler ben ngoai:  python -m src.retention   (chay tu thu muc ingestion/)
     hoac trong container:        python -m ingestion.src.retention
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from . import config
from .storage import LogStore

logger = logging.getLogger("ingestion.retention")

DEFAULT_RETENTION_DAYS = config.RETENTION_DAYS
DEFAULT_QUARANTINE_RETENTION_DAYS = config.QUARANTINE_RETENTION_DAYS


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def run_retention(store: LogStore, retention_days: int | None = None) -> int:
    """Drop cac daily index hoan toan cu hon cutoff; memory xoa log cu."""
    days = DEFAULT_RETENTION_DAYS if retention_days is None else retention_days
    return store.delete_older_than(_cutoff(days))


def run_quarantine_retention(store: LogStore, retention_days: int | None = None) -> int:
    """Xoa ban ghi quarantine co received_at cu hon cutoff. Tra so document da xoa."""
    days = DEFAULT_QUARANTINE_RETENTION_DAYS if retention_days is None else retention_days
    if days < 1:
        raise ValueError("quarantine retention_days must be >= 1")
    return store.delete_quarantine_older_than(_cutoff(days))


def run_all(store: LogStore) -> dict[str, int]:
    """Mot luot retention day du. Hai phan doc lap: loi o phan nay khong chan phan kia,
    nhung van duoc nem lai sau cung de job nen ghi log loi."""
    result: dict[str, int] = {}
    errors: list[Exception] = []
    for key, job in (("indices", run_retention), ("quarantine_docs", run_quarantine_retention)):
        try:
            result[key] = job(store)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    if errors:
        raise errors[0]
    return result


def start_scheduler(store: LogStore, interval_seconds: int | None = None) -> threading.Event | None:
    """Chay run_all dinh ky trong thread nen. Tra ve Event de dung (stop.set()).
    interval <= 0 -> khong chay (dung cron ben ngoai)."""
    interval = config.RETENTION_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
    if interval <= 0:
        return None
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            try:
                result = run_all(store)
                logger.info("retention: removed %d indices (or memory logs), retention=%d days; "
                            "quarantine: deleted %d docs, retention=%d days",
                            result["indices"], DEFAULT_RETENTION_DAYS,
                            result["quarantine_docs"], DEFAULT_QUARANTINE_RETENTION_DAYS)
            except Exception:  # noqa: BLE001 - job nen khong duoc chet vi loi tam thoi
                logger.exception("retention run failed")

    threading.Thread(target=loop, name="retention", daemon=True).start()
    return stop


if __name__ == "__main__":
    from .storage import build_store

    logging.basicConfig(level=logging.INFO)
    s = build_store()
    s.ensure_ready()
    r = run_all(s)
    print(f"deleted={r['indices']} retention_days={DEFAULT_RETENTION_DAYS} "
          f"quarantine_deleted={r['quarantine_docs']} "
          f"quarantine_retention_days={DEFAULT_QUARANTINE_RETENTION_DAYS}")
