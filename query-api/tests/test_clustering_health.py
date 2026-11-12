from datetime import datetime, timedelta, timezone
from importlib import import_module
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from ingestion.src.storage import StorageError

main = import_module("query-api.src.main")


@pytest.mark.parametrize("age, code, reason", [
    (None, 503, "missing"),
    (0, 200, None),
    (181, 503, "stale"),
    ("offline", 503, "storage_unavailable"),
])
def test_worker_health(monkeypatch, age, code, reason):
    store = Mock()
    processed_at = None
    if age == "offline":
        store.get_heartbeat.side_effect = StorageError("internal backend details")
    elif age is not None:
        processed_at = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    store.get_heartbeat.return_value = processed_at
    monkeypatch.setattr(main, "cluster_store", store)
    monkeypatch.setattr(main.config, "CLUSTER_HEARTBEAT_STALE_SECONDS", 180)
    response = TestClient(main.app).get("/clustering/health")
    assert response.status_code == code
    assert response.json() == {"status": "ok" if code == 200 else "degraded",
                               "reason": reason, "last_processed_at": processed_at}
    assert response.headers["Cache-Control"] == "no-store"
