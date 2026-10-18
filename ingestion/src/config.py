"""Cau hinh ingestion doc tu bien moi truong (khong hardcode)."""

from __future__ import annotations

import os


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# "opensearch" (mac dinh) hoac "memory" (chi de dev/test khong can OpenSearch)
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "opensearch").lower()

OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "")
OPENSEARCH_PASSWORD = os.environ.get("OPENSEARCH_PASSWORD", "")
OPENSEARCH_VERIFY_CERTS = _bool("OPENSEARCH_VERIFY_CERTS", False)
OPENSEARCH_TIMEOUT = int(os.environ.get("OPENSEARCH_TIMEOUT", "10"))

LOG_INDEX = os.environ.get("LOG_INDEX", "logs")
QUARANTINE_INDEX = os.environ.get("QUARANTINE_INDEX", "logs-quarantine")
NUMBER_OF_SHARDS = int(os.environ.get("OPENSEARCH_SHARDS", "1"))
NUMBER_OF_REPLICAS = int(os.environ.get("OPENSEARCH_REPLICAS", "0"))

# Retention: so ngay luu, va chu ky chay job nen (giay). 0 = khong tu chay (dung cron + python -m src.retention)
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))
RETENTION_INTERVAL_SECONDS = int(os.environ.get("RETENTION_INTERVAL_SECONDS", "3600"))

DEFAULT_SEARCH_LIMIT = int(os.environ.get("SEARCH_DEFAULT_LIMIT", "100"))
MAX_SEARCH_LIMIT = int(os.environ.get("SEARCH_MAX_LIMIT", "1000"))
