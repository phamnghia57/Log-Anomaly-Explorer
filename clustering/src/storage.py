"""Cluster storage using ingestion's configured OpenSearch client."""
import os

from ingestion.src.storage import OpenSearchLogStore, StorageError, build_store


class OpenSearchStore:
    def __init__(self, log_store=None):
        self.log_store = log_store if log_store is not None else build_store()
        if not isinstance(self.log_store, OpenSearchLogStore):
            raise ValueError("Clustering requires STORAGE_BACKEND=opensearch")
        self.client = self.log_store.client
        self.logs = self.log_store.log_index
        self.clusters = os.getenv("CLUSTER_INDEX", "clusters")
        self.history = os.getenv("HISTORY_INDEX", "cluster-history")

    def ensure_ready(self):
        self.log_store.ensure_ready()
        fields = {name: {"type": "keyword"} for name in
                  ("cluster_id", "signature", "log_ids", "trace_ids", "status")}
        fields.update(score={"type": "double"}, first_seen={"type": "date"}, last_seen={"type": "date"})
        try:
            if not self.client.indices.exists(index=self.clusters):
                self.client.indices.create(index=self.clusters, body={
                    "settings": self.log_store._settings(),
                    "mappings": {"dynamic": "strict", "properties": fields},
                })
        except Exception as exc:
            if "resource_already_exists_exception" not in str(exc):
                raise StorageError(f"cannot prepare clusters: {exc}") from exc

        # cluster-history-schema.json: 1 diem/chu ky/cum, KHONG upsert (khac
        # `clusters` o tren) - dung ve xu huong score theo thoi gian.
        history_fields = {"cluster_id": {"type": "keyword"}, "status": {"type": "keyword"},
                           "score": {"type": "double"}, "recorded_at": {"type": "date"}}
        try:
            if not self.client.indices.exists(index=self.history):
                self.client.indices.create(index=self.history, body={
                    "settings": self.log_store._settings(),
                    "mappings": {"dynamic": "strict", "properties": history_fields},
                })
        except Exception as exc:
            if "resource_already_exists_exception" not in str(exc):
                raise StorageError(f"cannot prepare cluster-history: {exc}") from exc

    def read_logs(self, start, end):
        scroll_id = None
        try:
            page = self.client.search(index=self.logs, scroll="2m", body={
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

        Read-only side of cluster-history-schema.json. The write side (one point
        appended per clustering cycle) is Nam's part, not implemented here yet -
        an empty list is a valid result until that lands.
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
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def close(self):
        self.client.close()
