"""Verify history reads and retention on OpenSearch using one temporary index."""
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from opensearchpy import OpenSearch

from clustering.src import alert
from clustering.src.incidents import IncidentRepository
from clustering.src.storage import OpenSearchStore
from ingestion.src.storage import OpenSearchLogStore


def main():
    url = os.environ["LIVE_TEST_OPENSEARCH_URL"]
    client = OpenSearch(url, timeout=30, max_retries=0)
    index = "codex-history-test-" + uuid4().hex
    store = OpenSearchStore(OpenSearchLogStore(client))
    store.history = index
    store.clusters = index + "-clusters"
    incident_index = store.clusters + "-incidents"
    heartbeat_index = store.heartbeat
    assert incident_index.startswith("codex-history-test-")
    assert heartbeat_index.startswith("codex-history-test-")
    created_indices = []
    try:
        client.indices.create(index=index, body={"mappings": {"dynamic": "strict", "properties": {
            "cluster_id": {"type": "keyword"}, "score": {"type": "double"},
            "status": {"type": "keyword"}, "recorded_at": {"type": "date"},
        }}})
        created_indices.append(index)
        for day in (1, 2, 3):
            store.write_history({"cluster_id": "c1", "score": day, "status": "normal"},
                                f"2026-01-0{day}T00:00:00Z")
        store.write_history({"cluster_id": "c2", "score": 9, "status": "normal"}, "2026-01-03T00:00:00Z")
        assert [p["score"] for p in store.list_history("c1", limit=2)] == [2, 3]
        assert store.delete_history_before("2026-01-02T00:00:00Z") == 1
        client.indices.refresh(index=index)
        assert [p["score"] for p in store.list_history("c1")] == [2, 3]
        assert [p["score"] for p in store.list_history("c2")] == [9]
        print("PASS: latest history and retention cutoff (point exactly at cutoff retained)")
        bulk = []
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        for minute in range(1, 151):
            bulk.extend([{"index": {"_index": index}}, {
                "cluster_id": "c150", "score": minute, "status": "normal",
                "recorded_at": (start + timedelta(minutes=minute)).isoformat(),
            }])
        assert not client.bulk(body=bulk)["errors"]
        client.indices.refresh(index=index)
        assert [p["score"] for p in store.list_history("c150", limit=100)] == list(range(51, 151))
        assert [p["score"] for p in store.list_history("c150", limit=50)] == list(range(101, 151))
        assert [p["score"] for p in store.list_history(
            "c150", since=(start + timedelta(minutes=140)).isoformat(), limit=100
        )] == list(range(140, 151))
        print("PASS: 150 synthetic minute points; latest 100 = 51..150; latest 50 = 101..150; since inclusive")
        client.indices.create(index=heartbeat_index, body={"mappings": {"dynamic": "strict", "properties": {
            "last_processed_at": {"type": "date"}, "window_to": {"type": "date"},
            "cycle_seconds": {"type": "double"}, "logs_read": {"type": "long"}, "clusters_out": {"type": "long"},
        }}})
        created_indices.append(heartbeat_index)
        store.write_heartbeat("2026-01-03T00:00:00Z", window_to="2026-01-03T00:00:00Z",
                              cycle_seconds=1.25, logs_read=12, clusters_out=3)
        heartbeat = client.get(index=heartbeat_index, id="worker")["_source"]
        assert heartbeat["cycle_seconds"] == 1.25 and heartbeat["logs_read"] == 12
        print("PASS: heartbeat metrics persisted on real OpenSearch")
        incidents = IncidentRepository(store)
        incidents.ensure_ready()
        created_indices.append(incident_index)
        cluster = {"cluster_id": "c1", "service": "test", "signature": "test error",
                   "score": 5, "status": "anomalous", "first_seen": "2026-01-03T00:00:00Z",
                   "last_seen": "2026-01-03T00:00:30Z"}
        incident = incidents.current(cluster)
        incidents.apply(cluster, incident["episode_id"], "acknowledge", "test-user")
        assert incidents.current(cluster)["status"] == "acknowledged"
        os.environ["ANOMALY_THRESHOLD"] = "2"
        os.environ["ALERT_WEBHOOK_URL"] = "http://unused.invalid/webhook"
        def unexpected_webhook(*args, **kwargs):
            raise AssertionError("acknowledged incident must not trigger webhook")
        alert.httpx.post = unexpected_webhook
        assert alert.check_and_alert_batch([("test", cluster)], incidents=incidents) == 0
        assert cluster["status"] == "anomalous"
        print("PASS: acknowledged incident suppresses webhook on real OpenSearch")
    finally:
        for created_index in created_indices:
            assert created_index.startswith("codex-history-test-")
            client.indices.delete(index=created_index)
        client.close()
    print("PASS: temporary test indices cleaned up; no webhook delivery or production data used")


if __name__ == "__main__":
    main()
