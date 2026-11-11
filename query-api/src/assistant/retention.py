"""Retention job cho index hoi thoai AI Assistant.

Khac `logs` (ingestion/src/retention.py drop ca index theo ngay): index
`assistant-conversations` chi co toi da 1 document cho moi cum da tung duoc
hoi, khoi luong nho nen xoa theo `updated_at` bang delete_by_query la du.

So ngay luu lay tu ASSISTANT_RETENTION_DAYS (khong hardcode).

Hai cach chay dinh ky:
  1. Tu dong trong service: main.py khoi dong vong lap nen, chu ky
     ASSISTANT_RETENTION_INTERVAL_SECONDS.
  2. Cron / scheduler ben ngoai (dat interval = 0 de tat vong lap nen):
         python -m query-api.src.assistant.retention   (chay tu thu muc goc repo)
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from . import config

logger = logging.getLogger("query-api.assistant.retention")


def run_retention(repository, retention_days: int | None = None) -> int:
    """Xoa hoi thoai khong duoc dung toi trong `retention_days` ngay qua.

    Moc so sanh la `updated_at` (lan hoi gan nhat), khong phai `created_at`:
    hoi thoai dang duoc dung tiep thi khong bi xoa du tao da lau.
    """
    days = config.CONVERSATIONS_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return repository.delete_older_than(cutoff.isoformat())


def start_scheduler(repository, interval_seconds: int | None = None) -> threading.Event | None:
    """Chay run_retention dinh ky trong thread nen. Tra ve Event de dung (stop.set()).
    interval <= 0 -> khong chay (dung cron ben ngoai)."""
    interval = (config.CONVERSATIONS_RETENTION_INTERVAL_SECONDS
                if interval_seconds is None else interval_seconds)
    if interval <= 0:
        return None
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            try:
                deleted = run_retention(repository)
                logger.info("assistant retention: da xoa %d hoi thoai cu hon %d ngay",
                            deleted, config.CONVERSATIONS_RETENTION_DAYS)
            except Exception:  # noqa: BLE001 - job nen khong duoc chet vi loi tam thoi
                logger.exception("assistant retention that bai")

    threading.Thread(target=loop, name="assistant-retention", daemon=True).start()
    return stop


if __name__ == "__main__":
    from .storage import ConversationRepository

    logging.basicConfig(level=logging.INFO)
    repo = ConversationRepository()
    repo.ensure_ready()
    print(f"deleted={run_retention(repo)} retention_days={config.CONVERSATIONS_RETENTION_DAYS}")
