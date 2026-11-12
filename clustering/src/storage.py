"""Cluster storage using ingestion's configured OpenSearch client."""
import os

from ingestion.src.storage import OpenSearchLogStore, StorageError, build_store


class OpenSearchStore:
    def __init__(self, log_store=None):
        self.log_store = log_store if log_store is not None else build_store()
        if not isinstance(self.log_store, OpenSearchLogStore):
            raise ValueError("Clustering requires STORAGE_BACKEND=opensearch")
        self.client = self.log_store.client
        self.logs = self.log_store.read_indices
        self.clusters = os.getenv("CLUSTER_INDEX", "clusters")
        self.history = os.getenv("HISTORY_INDEX", "cluster-history")

    @property
    def heartbeat(self):
        return f"{self.clusters}-heartbeat"

    def _ensure_index(self, index, fields):
        try:
            if not self.client.indices.exists(index=index):
                self.client.indices.create(index=index, body={
                    "settings": self.log_store._settings(),
                    "mappings": {"dynamic": "strict", "properties": fields},
                })
        except Exception as exc:
            if "resource_already_exists_exception" not in str(exc):
                raise StorageError(f"cannot prepare {index}") from exc

    def ensure_ready(self):
        self.log_store.ensure_ready()
        fields = {name: {"type": "keyword"} for name in
                  ("cluster_id", "service", "signature", "log_ids", "trace_ids", "status")}
        fields.update(score={"type": "double"}, first_seen={"type": "date"}, last_seen={"type": "date"})
        self._ensure_index(self.clusters, fields)

        # cluster-history-schema.json: 1 diem/chu ky/cum, KHONG upsert (khac
        # `clusters` o tren) - dung ve xu huong score theo thoi gian.
        evidence_fields = {key: {"type": "date"} for key in ("first_seen", "last_seen")}
        history_fields = {"cluster_id": {"type": "keyword"}, "status": {"type": "keyword"},
                           "score": {"type": "double"}, "recorded_at": {"type": "date"},
                           **evidence_fields}
        self._ensure_index(self.history, history_fields)
        try:
            self.client.indices.put_mapping(index=self.history, body={"properties": evidence_fields})
        except Exception as exc:
            raise StorageError("cannot migrate cluster history timestamps") from exc
        self._ensure_index(self.heartbeat, {"last_processed_at": {"type": "date"}})

    def write_heartbeat(self, processed_at):
        try:
            self.client.index(index=self.heartbeat, id="worker", body={"last_processed_at": processed_at})
        except Exception as exc:
            raise StorageError("cannot write clustering heartbeat") from exc

    def get_heartbeat(self):
        try:
            response = self.client.get(index=self.heartbeat, id="worker", ignore=[404])
            return response["_source"]["last_processed_at"] if response.get("found") else None
        except Exception as exc:
            raise StorageError("cannot read clustering heartbeat") from exc

    def read_logs(self, start, end):
        scroll_id = None
        try:
            page = self.client.search(index=self.logs, scroll="2m",
                                      ignore_unavailable=True, allow_no_indices=True, body={
                "size": 1000, "sort": ["_doc"], "query": {"bool": {"filter": [
                    {"range": {"timestamp": {"gte": start, "lt": end}}},
                    {"terms": {"level": ["ERROR", "FATAL"]}},
                ]}},
            })
            while True:
                scroll_id = page.get("_scroll_id", scroll_id)
                if page.get("timed_out") or page.get("_shards", {}).get("failed", 0):
                    raise RuntimeError("Incomplete OpenSearch search; refusing partial baseline")
                hits = page["hits"]["hits"]
                if not hits:
                    break
                for hit in hits:
                    yield {**hit["_source"], "log_id": hit["_id"]}
                if not scroll_id:
                    raise RuntimeError("Search did not return scroll ID")
                page = self.client.scroll(scroll="2m", scroll_id=scroll_id)
        finally:
            if scroll_id:
                self.client.clear_scroll(body={"scroll_id": [scroll_id]})

    def write_cluster(self, record):
        """Upsert the latest window for a stable cluster ID."""
        try:
            self.client.index(index=self.clusters, id=record["cluster_id"],
                              body=record, refresh="wait_for")
        except Exception as exc:
            raise StorageError(f"write_cluster failed: {exc}") from exc

    def write_history(self, record, recorded_at):
        """Append one score point for a cluster at the cycle's window_to."""
        point = {name: record[name] for name in ("cluster_id", "score", "status")}
        point.update({name: record[name] for name in ("first_seen", "last_seen") if name in record})
        point["recorded_at"] = recorded_at
        try:
            self.client.index(index=self.history, body=point, refresh="wait_for")
        except Exception as exc:
            raise StorageError(f"write_history failed: {exc}") from exc

    def list_clusters(self, *, status=None, since=None, limit=100, offset=0):
        """Return records by last_seen descending; since includes that instant."""
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset nonnegative")
        filters = []
        if status is not None:
            if status not in {"normal", "anomalous", "alerted"}:
                raise ValueError("Invalid cluster status")
            filters.append({"term": {"status": status}})
        if since is not None:
            filters.append({"range": {"last_seen": {"gte": since}}})
        body = {"query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                "sort": [{"last_seen": "desc"}, {"cluster_id": "asc"}],
                "size": limit, "from": offset}
        try:
            response = self.client.search(index=self.clusters, body=body)
        except Exception as exc:
            raise StorageError(f"list_clusters failed: {exc}") from exc
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def get_cluster(self, cluster_id):
        """Return a ClusterRecord, or None when the ID does not exist."""
        try:
            response = self.client.get(index=self.clusters, id=cluster_id, ignore=[404])
        except Exception as exc:
            raise StorageError(f"get_cluster failed: {exc}") from exc
        return response["_source"] if response.get("found") else None

    def list_history(self, cluster_id, *, since=None, limit=100):
        """Return ClusterHistoryPoint[] for one cluster, oldest first (chart order).
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        filters = [{"term": {"cluster_id": cluster_id}}]
        if since is not None:
            filters.append({"range": {"recorded_at": {"gte": since}}})
        body = {"query": {"bool": {"filter": filters}},
                "sort": [{"recorded_at": "asc"}], "size": limit}
        try:
            response = self.client.search(index=self.history, body=body)
        except Exception as exc:
            raise StorageError(f"list_history failed: {exc}") from exc
        return [{field: hit["_source"][field] for field in ("cluster_id", "score", "status", "recorded_at")}
                for hit in response["hits"]["hits"]]

    def first_anomaly_after(self, cluster_id, resolved_at):
        body = {
            "size": 1,
            "query": {"bool": {"filter": [
                {"term": {"cluster_id": cluster_id}},
                {"terms": {"status": ["anomalous", "alerted"]}},
                {"range": {"last_seen": {"gt": resolved_at}}},
            ]}},
            "sort": [{"last_seen": {"order": "asc", "unmapped_type": "date"}}, {"recorded_at": "asc"}],
        }
        try:
            hits = self.client.search(index=self.history, body=body, ignore_unavailable=True)["hits"]["hits"]
            return hits[0]["_source"] if hits else None
        except Exception as exc:
            raise StorageError("cannot read incident recurrence") from exc

    def close(self):
        self.client.close()
