"""OpenSearch adapter. Only ClusterRecord fields are written to the clusters index."""
import os
from urllib.parse import quote
import httpx


class OpenSearchStore:
    def __init__(self):
        user = os.getenv("OPENSEARCH_USER", "")
        self.client = httpx.Client(
            base_url=os.getenv("OPENSEARCH_URL", "http://localhost:9200").rstrip("/"),
            auth=(user, os.getenv("OPENSEARCH_PASSWORD", "")) if user else None,
            verify=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true",
            timeout=30,
        )
        self.logs = quote(os.getenv("LOG_INDEX", "logs"), safe="")
        self.clusters = quote(os.getenv("CLUSTER_INDEX", "clusters"), safe="")

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def ensure_ready(self):
        response = self.client.head(f"/{self.clusters}")
        if response.status_code != 404:
            response.raise_for_status()
            return
        fields = {name: {"type": "keyword"} for name in
                  ("cluster_id", "signature", "log_ids", "trace_ids", "status")}
        fields.update(score={"type": "double"}, first_seen={"type": "date"}, last_seen={"type": "date"})
        self.request("PUT", f"/{self.clusters}", json={"mappings": {"dynamic": "strict", "properties": fields}})

    def read_logs(self, start, end):
        scroll_id = None
        try:
            page = self.request("POST", f"/{self.logs}/_search", params={"scroll": "2m"}, json={
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
                page = self.request("POST", "/_search/scroll", json={"scroll": "2m", "scroll_id": scroll_id})
        finally:
            if scroll_id:
                self.client.request("DELETE", "/_search/scroll", json={"scroll_id": [scroll_id]})

    def write_cluster(self, record):
        # Latest observed window per stable service/signature ID; upsert is idempotent.
        self.request("PUT", f"/{self.clusters}/_doc/{record['cluster_id']}", json=record,
                     params={"refresh": "wait_for"})

    def close(self):
        self.client.close()
