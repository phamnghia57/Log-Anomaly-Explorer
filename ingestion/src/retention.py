"""
Retention job - xoa log qua han.

TODO (Minh): chay job nay dinh ky (cron / scheduler). So ngay luu
lay tu bien moi truong RETENTION_DAYS de khong hardcode theo tung bien the ca nhan.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .storage import LogStore

DEFAULT_RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))


def run_retention(store: LogStore, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Xoa moi log cu hon `retention_days` ngay. Tra ve so log da xoa."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    return store.delete_older_than(cutoff.isoformat())
