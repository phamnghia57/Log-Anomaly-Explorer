"""Verify cycle orchestration without OpenSearch or external webhooks."""
import sys
from clustering.src import worker


def test_cycle_batches_alerts_then_appends_final_status(monkeypatch):
    calls = []
    records = [("web", {"cluster_id": "c1", "score": 5, "status": "anomalous"}),
               ("api", {"cluster_id": "c2", "score": 1, "status": "normal"})]
    class Store:
        def ensure_ready(self): pass
        def read_logs(self, start, end): return []
        def write_cluster(self, record):
            calls.append(("cluster", record["cluster_id"], record["status"]))
        def write_history(self, record, end):
            calls.append(("history", record["cluster_id"], record["status"], end))
        def close(self): calls.append(("close",))
    def send(batch, *, window_to):
        assert batch is records
        calls.append(("digest", window_to))
        batch[0][1]["status"] = "alerted"
    monkeypatch.setattr(sys, "argv", ["worker", "--window-to", "2026-10-26T00:01:00Z"])
    monkeypatch.setenv("ML_AUGMENT_ENABLED", "false")
    monkeypatch.setattr(worker, "OpenSearchStore", Store)
    monkeypatch.setattr(worker, "analyze", lambda *a, **kw: records)
    monkeypatch.setattr(worker, "check_and_alert_batch", send)
    worker.main()
    assert [c for c in calls if c[0] == "digest"] == [("digest", "2026-10-26T00:01:00+00:00")]
    assert [c for c in calls if c[0] == "history"] == [
        ("history", "c1", "alerted", "2026-10-26T00:01:00+00:00"),
        ("history", "c2", "normal", "2026-10-26T00:01:00+00:00")]
    assert calls[-1] == ("close",)


def test_live_cycle_without_clusters_still_writes_heartbeat(monkeypatch):
    from datetime import datetime
    from unittest.mock import Mock

    store = Mock()
    store.read_logs.return_value = []
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])
    monkeypatch.setenv("ML_AUGMENT_ENABLED", "false")
    monkeypatch.setattr(worker, "OpenSearchStore", lambda: store)
    worker.main()
    store.write_heartbeat.assert_called_once()
    timestamp = datetime.fromisoformat(store.write_heartbeat.call_args.args[0])
    assert timestamp.tzinfo is not None
    store.write_history.assert_not_called()
