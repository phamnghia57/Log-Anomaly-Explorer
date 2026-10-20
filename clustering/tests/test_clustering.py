import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation"))
from src.clustering import group_similar_errors, make_cluster_id, normalize_message
from src.anomaly_score import baseline_from_history, compute_anomaly_score
from src.pipeline import analyze
from src.alert import check_and_alert, reset_alert_state, get_threshold
from src.storage import OpenSearchStore
from precision_recall import evaluate, _cluster_overlaps_incident
from synthetic_demo import sample_logs


class PipelineTests(unittest.TestCase):
    def test_normalization_and_service_isolation(self):
        logs = sample_logs()
        self.assertEqual(normalize_message("User 12 not found"), normalize_message("User 34 not found"))
        groups = group_similar_errors(logs + [{**logs[0], "service": "other"}, {**logs[0], "level": "INFO"}])
        self.assertEqual(len(groups), 3)
        self.assertNotEqual(make_cluster_id("a", "x"), make_cluster_id("b", "x"))

    def test_spike_baseline_links_and_deduplication(self):
        logs = sample_logs()
        records = analyze(logs + logs, "2026-10-01T09:03:00Z", history_windows=2)
        record = next(r for _, r in records if r["signature"].startswith("Payment"))
        self.assertAlmostEqual(record["score"], 4.243)
        self.assertEqual(record["status"], "anomalous")
        self.assertEqual(len(record["log_ids"]), 8)
        self.assertEqual(len(record["trace_ids"]), 8)
        self.assertEqual(set(record), {"cluster_id", "signature", "score", "status", "log_ids", "trace_ids", "first_seen", "last_seen"})

    def test_boundaries_and_zero_windows(self):
        log = sample_logs()[0]
        logs = [{**log, "timestamp": "2026-10-01T09:02:00Z"},
                {**log, "log_id": "excluded", "timestamp": "2026-10-01T09:03:00Z"}]
        record = analyze(logs, "2026-10-01T09:03:00Z", history_windows=2)[0][1]
        self.assertEqual(record["score"], 1.0)
        self.assertEqual(record["log_ids"], [log["log_id"]])
        self.assertEqual(baseline_from_history([0, 0, 3])[0], 1)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            compute_anomaly_score("x", [], 0)
        with self.assertRaises(ValueError):
            baseline_from_history([-1])
        with self.assertRaises(ValueError):
            analyze(sample_logs(), "2026-10-01T09:03:00Z", window_seconds=0)


class AlertTests(unittest.TestCase):
    def setUp(self):
        reset_alert_state()
        self.cluster = {"cluster_id": "x", "score": 3, "first_seen": "2026-10-01T09:00:00Z"}
        self.env = patch.dict(os.environ, {"ANOMALY_THRESHOLD": "2", "ALERT_WEBHOOK_URL": "https://example.test/hook", "ALERT_COOLDOWN_SECONDS": "600"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        reset_alert_state()

    def test_success_payload_and_cooldown(self):
        response = httpx.Response(200, request=httpx.Request("POST", "https://example.test/hook"))
        with patch("src.alert.httpx.post", return_value=response) as post:
            self.assertTrue(check_and_alert(self.cluster, "demo-web"))
            self.assertFalse(check_and_alert(self.cluster, "demo-web"))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs["json"]["service"], "demo-web")
            self.assertEqual(self.cluster["status"], "alerted")

    def test_failure_is_retryable(self):
        response = httpx.Response(500, request=httpx.Request("POST", "https://example.test/hook"))
        with patch("src.alert.httpx.post", return_value=response) as post:
            self.assertFalse(check_and_alert(self.cluster))
            self.assertFalse(check_and_alert(self.cluster))
            self.assertEqual(post.call_count, 2)
            self.assertEqual(self.cluster["status"], "anomalous")

    def test_missing_webhook_threshold_and_nan(self):
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": ""}):
            self.assertFalse(check_and_alert(self.cluster))
            self.assertEqual(self.cluster["status"], "anomalous")
        self.cluster["score"] = 2
        self.assertFalse(check_and_alert(self.cluster))
        self.assertEqual(self.cluster["status"], "normal")
        with patch.dict(os.environ, {"ANOMALY_THRESHOLD": "nan"}):
            self.assertEqual(get_threshold(), 2)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.labels = ROOT / "evaluation/synthetic_incidents.json"
        self.predictions = [r for _, r in analyze(sample_logs(), "2026-10-01T09:03:00Z", history_windows=2)]

    def test_synthetic_pipeline(self):
        result = evaluate(self.predictions, self.labels)
        self.assertEqual(result, {"precision": 1.0, "recall": 1.0, "true_positive": 1, "false_positive": 0, "false_negative": 0})

    def test_duplicates_are_false_positives(self):
        anomalous = next(r for r in self.predictions if r["status"] == "anomalous")
        result = evaluate([anomalous, anomalous], self.labels)
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["true_positive"], 1)

    def test_wrong_service_and_time_do_not_match(self):
        incident = json.loads(self.labels.read_text(encoding="utf-8-sig"))["incidents"][0]
        cluster = next(r for r in self.predictions if r["status"] == "anomalous")
        self.assertFalse(_cluster_overlaps_incident({**cluster, "cluster_id": "wrong-service"}, incident))
        self.assertFalse(_cluster_overlaps_incident({**cluster, "first_seen": "2026-10-01T09:03:00Z", "last_seen": "2026-10-01T09:03:00Z"}, incident))
        self.assertEqual(evaluate([], self.labels)["false_negative"], 1)
        self.assertEqual(evaluate([cluster], self.labels, statuses=("alerted",))["false_negative"], 1)


class StorageTests(unittest.TestCase):
    def test_scroll_keeps_ids_and_cleans_up(self):
        calls = []
        def handle(request):
            calls.append(request)
            if request.url.path.endswith("/_search"):
                return httpx.Response(200, json={"_scroll_id": "s", "hits": {"hits": [{"_id": "stored-id", "_source": {"message": "error"}}]}})
            return httpx.Response(200, json={"_scroll_id": "s", "hits": {"hits": []}})
        store = OpenSearchStore()
        store.client.close()
        store.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle))
        try:
            self.assertEqual(list(store.read_logs("a", "b"))[0]["log_id"], "stored-id")
            self.assertEqual(calls[-1].method, "DELETE")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
