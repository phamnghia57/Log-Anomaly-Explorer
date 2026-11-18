from clustering.evaluation.sweep import measure
from clustering.src.clustering import make_cluster_id


def test_metrics_cooldown_quiet_and_delay():
    signature = "fault"
    cluster = {"cluster_id": make_cluster_id("web", signature), "signature": signature,
               "service": "web", "score": 3, "status": "anomalous",
               "first_seen": "2026-01-01T00:00:05Z", "last_seen": "2026-01-01T00:00:50Z"}
    labels = {"incidents": [{"incident_id": "i", "service": "web", "expected_cluster_signature": signature,
                              "window_from": "2026-01-01T00:00:00Z", "window_to": "2026-01-01T00:01:00Z"}],
              "quiet_intervals": [{"window_from": "2026-01-01T00:01:00Z", "window_to": "2026-01-01T01:01:00Z"}]}
    quiet = {**cluster, "first_seen": "2026-01-01T00:10:10Z", "last_seen": "2026-01-01T00:10:30Z"}
    result, alerts = measure([("2026-01-01T00:01:00Z", cluster),
                              ("2026-01-01T00:02:00Z", quiet),
                              ("2026-01-01T00:11:00Z", quiet)], labels, 2)
    assert result["precision"] == 0.5
    assert result["recall"] == 1
    assert result["false_alerts_per_hour"] == 1
    assert result["mean_detection_delay_windows"] == 1
    assert len(alerts) == 2
