"""Verify cycle orchestration without OpenSearch or external webhooks."""
import sys
import pytest
from clustering.src import worker


def test_cycle_batches_alerts_then_appends_final_status(monkeypatch):
    calls = []
    records = [("web", {"cluster_id": "c1", "score": 5, "status": "anomalous"}),
               ("api", {"cluster_id": "c2", "score": 1, "status": "normal"})]
    class Store:
        def ensure_ready(self): pass
        def read_logs(self, start, end): return []
        def write_cycle(self, cycle, end):
            calls.append(("cycle", [(r["cluster_id"], r["status"]) for r in cycle], end))
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
    assert calls == [("digest", "2026-10-26T00:01:00+00:00"),
                     ("cycle", [("c1", "alerted"), ("c2", "normal")], "2026-10-26T00:01:00+00:00"),
                     ("close",)]


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
    store.write_cycle.assert_called_once_with([], metrics["window_to"])


@pytest.mark.parametrize("outcomes, expected_signals", [
    ([False, None, True], [True, False, False]),
    ([False, None, None, None, None, None], [True, False, False, False, False, False]),
    ([False, False, None], [True, True, False]),
])
def test_failure_signal_is_not_overwritten_within_the_same_cycle(monkeypatch, outcomes, expected_signals):
    from unittest.mock import Mock
    store = Mock()
    store.read_logs.return_value = []
    monkeypatch.setattr(sys, "argv", ["worker"])
    monkeypatch.setenv("ML_AUGMENT_ENABLED", "false")
    monkeypatch.setattr(worker, "OpenSearchStore", lambda: store)
    monkeypatch.setattr(worker, "analyze", lambda *a, **kw: [])
    signals = []
    monkeypatch.setattr(worker, "ping", lambda **kw: signals.append(kw.get("failed", False)))
    cycles = len(outcomes)
    outcomes = iter(outcomes)
    def send(*args, on_delivery, **kwargs):
        result = next(outcomes)
        if result is not None:
            on_delivery(result)
    monkeypatch.setattr(worker, "check_and_alert_batch", send)
    def sleep(_):
        if store.write_heartbeat.call_count == cycles:
            raise KeyboardInterrupt
    monkeypatch.setattr(worker.time, "sleep", sleep)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        worker.main()
    assert signals == expected_signals
    assert store.write_heartbeat.call_count == cycles


def test_incident_storage_failure_does_not_interrupt_live_cycle(monkeypatch, caplog):
    import httpx
    from unittest.mock import Mock
    from clustering.src import alert

    store = Mock()
    store.read_logs.return_value = []
    store.get_alert_times.return_value = {}
    store.delete_history_before.return_value = 0
    incidents = Mock()
    incidents.current.side_effect = worker.StorageError("private-storage-details")
    cluster = {"cluster_id": "c1", "score": 5, "status": "anomalous",
               "first_seen": "2026-11-19T00:00:00Z"}
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])
    monkeypatch.setenv("ML_AUGMENT_ENABLED", "false")
    monkeypatch.setenv("ANOMALY_THRESHOLD", "2")
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://webhook.test/hook")
    monkeypatch.setattr(worker, "OpenSearchStore", lambda: store)
    monkeypatch.setattr(worker, "IncidentRepository", lambda store: incidents)
    monkeypatch.setattr(worker, "analyze", lambda *a, **kw: [("web", cluster)])
    post = Mock(return_value=httpx.Response(200, request=httpx.Request("POST", "http://webhook.test/hook")))
    ping = Mock()
    monkeypatch.setattr(alert.httpx, "post", post)
    monkeypatch.setattr(worker, "ping", ping)

    worker.main()

    post.assert_called_once()
    store.write_alert_times.assert_called_once()
    store.write_cycle.assert_called_once()
    assert store.write_cycle.call_args.args[0] == [cluster]
    store.write_heartbeat.assert_called_once()
    store.close.assert_called_once()
    ping.assert_called_once_with()
    assert cluster["status"] == "alerted"
    assert "Cannot read incident state for c1" in caplog.text
    assert "private-storage-details" not in caplog.text


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
