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
    def send(batch, *, window_to, store, incidents, on_delivery):
        assert isinstance(store, Store)
        assert batch is records
        calls.append(("digest", window_to))
        batch[0][1]["status"] = "alerted"
    monkeypatch.setattr(sys, "argv", ["worker", "--window-to", "2026-10-26T00:01:00Z"])
    monkeypatch.setenv("ML_AUGMENT_ENABLED", "false")
    monkeypatch.setattr(worker, "OpenSearchStore", Store)
    monkeypatch.setattr(worker, "IncidentRepository", lambda store: object())
    monkeypatch.setattr(worker, "analyze", lambda *a, **kw: records)
    monkeypatch.setattr(worker, "check_and_alert_batch", send)
    worker.main()
    assert [c for c in calls if c[0] == "digest"] == [("digest", "2026-10-26T00:01:00+00:00")]
    assert [c for c in calls if c[0] == "cluster"] == [("cluster", "c1", "alerted"),
                                                        ("cluster", "c2", "normal")]
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
    store.delete_history_before.assert_called_once()
    timestamp = datetime.fromisoformat(store.write_heartbeat.call_args.args[0])
    assert timestamp.tzinfo is not None
    metrics = store.write_heartbeat.call_args.kwargs
    assert metrics["cycle_seconds"] >= 0
    assert metrics["logs_read"] == 0 and metrics["clusters_out"] == 0
    store.write_history.assert_not_called()


def test_failure_signal_is_not_immediately_overwritten_and_recovers_on_delivery(monkeypatch):
    from unittest.mock import Mock
    store = Mock()
    store.read_logs.return_value = []
    monkeypatch.setattr(sys, "argv", ["worker"])
    monkeypatch.setenv("ML_AUGMENT_ENABLED", "false")
    monkeypatch.setattr(worker, "OpenSearchStore", lambda: store)
    monkeypatch.setattr(worker, "analyze", lambda *a, **kw: [])
    signals = []
    monkeypatch.setattr(worker, "ping", lambda **kw: signals.append(kw.get("failed", False)))
    outcomes = iter([False, None, True])
    def send(*args, on_delivery, **kwargs):
        result = next(outcomes)
        if result is not None:
            on_delivery(result)
    monkeypatch.setattr(worker, "check_and_alert_batch", send)
    def sleep(_):
        if store.write_heartbeat.call_count == 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(worker.time, "sleep", sleep)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        worker.main()
    assert signals == [True, False]
    assert store.write_heartbeat.call_count == 3


def test_retention_runs_at_most_hourly_and_retries_failure(monkeypatch):
    from unittest.mock import Mock
    import pytest
    store = Mock()
    store.read_logs.return_value = []
    store.delete_history_before.side_effect = [worker.StorageError("offline"), 3]
    clock = [100.0]
    monkeypatch.setattr(sys, "argv", ["worker"])
    monkeypatch.setenv("ML_AUGMENT_ENABLED", "false")
    monkeypatch.setenv("RETENTION_DAYS", "7")
    monkeypatch.setattr(worker, "OpenSearchStore", lambda: store)
    monkeypatch.setattr(worker, "analyze", lambda *a, **kw: [])
    monkeypatch.setattr(worker, "check_and_alert_batch", lambda *a, **kw: 0)
    monkeypatch.setattr(worker, "ping", lambda **kw: None)
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    def sleep(_):
        if store.write_heartbeat.call_count == 1:
            clock[0] = 3699.0
        elif store.write_heartbeat.call_count == 2:
            clock[0] = 3700.0
        else:
            raise KeyboardInterrupt
    monkeypatch.setattr(worker.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        worker.main()
    assert store.write_heartbeat.call_count == 3
    assert store.delete_history_before.call_count == 2
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.fromisoformat(store.delete_history_before.call_args.args[0])
    assert abs((datetime.now(timezone.utc) - cutoff - timedelta(days=7)).total_seconds()) < 5
