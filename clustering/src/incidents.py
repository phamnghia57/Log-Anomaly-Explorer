"""Operator-managed incident episodes backed by the cluster history."""

from datetime import datetime, timedelta, timezone

from opensearchpy.exceptions import ConflictError, NotFoundError
from opensearchpy.helpers import scan

from ingestion.src.storage import StorageError


class IncidentConflict(Exception):
    pass


def utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


class IncidentRepository:
    def __init__(self, clusters):
        self.clusters = clusters
        self.client = clusters.client
        self.index = f"{clusters.clusters}-incidents"

    def ensure_ready(self):
        fields = {name: {"type": "keyword"} for name in (
            "episode_id", "cluster_id", "service", "signature", "status", "disposition",
            "acknowledged_by", "resolved_by",
        )}
        fields.update({name: {"type": "date"} for name in (
            "window_from", "window_to", "acknowledged_at", "resolved_at",
        )})
        fields.update(episode={"type": "integer"}, note={"type": "text", "index": False})
        self.clusters._ensure_index(self.index, fields)

    def _get(self, episode_id):
        try:
            return self.client.get(index=self.index, id=episode_id, realtime=True)
        except NotFoundError:
            return None
        except Exception:
            raise StorageError("cannot read incident episode") from None

    def _current(self, cluster):
        cluster_id = cluster["cluster_id"]
        try:
            hits = self.client.search(index=self.index, ignore_unavailable=True, body={
                "size": 1, "query": {"term": {"cluster_id": cluster_id}},
                "sort": [{"episode": {"order": "desc", "unmapped_type": "integer"}}],
            })["hits"]["hits"]
        except Exception:
            raise StorageError("cannot find current incident episode") from None
        episode = hits[0]["_source"]["episode"] if hits else 1
        record = self._get(f"{cluster_id}:{episode}")
        evidence = cluster
        cutoff = None
        while record:
            current = record["_source"]
            if current["status"] != "resolved":
                return current, record
            cutoff = current["resolved_at"]
            evidence = self.clusters.first_anomaly_after(cluster_id, cutoff)
            if evidence is None:
                return current, record
            episode += 1
            record = self._get(f"{cluster_id}:{episode}")

        start = utc_timestamp(evidence["first_seen"])
        if cutoff:
            start = max(start, utc_timestamp(cutoff))
        end = utc_timestamp(evidence["last_seen"]) + timedelta(milliseconds=1)
        return {
            "episode_id": f"{cluster_id}:{episode}", "episode": episode,
            "cluster_id": cluster_id, "service": cluster["service"], "signature": cluster.get("signature", ""),
            "status": "open", "window_from": start.isoformat(), "window_to": end.isoformat(),
        }, None

    def current(self, cluster):
        return self._current(cluster)[0]

    def apply(self, cluster, episode_id, action, actor, resolution=None):
        self.ensure_ready()
        for _ in range(8):
            current, record = self._current(cluster)
            if current["episode_id"] != episode_id:
                raise IncidentConflict("Incident episode has changed")
            now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            if action == "acknowledge":
                if current["status"] == "acknowledged":
                    return current
                if current["status"] != "open":
                    raise IncidentConflict("Incident has already been resolved")
                changes = {"status": "acknowledged", "acknowledged_by": actor, "acknowledged_at": now}
            else:
                if current["status"] == "resolved":
                    if all(current[field] == value for field, value in resolution.items()):
                        return current
                    raise IncidentConflict("Incident has already been resolved")
                changes = {**resolution, "status": "resolved", "resolved_by": actor, "resolved_at": now}

            updated = {**current, **changes}
            try:
                if record is None:
                    self.client.create(index=self.index, id=episode_id, body=updated, refresh="wait_for")
                else:
                    self.client.index(index=self.index, id=episode_id, body=updated, refresh="wait_for",
                                      if_seq_no=record["_seq_no"], if_primary_term=record["_primary_term"])
            except ConflictError:
                continue
            except Exception:
                raise StorageError("cannot save incident episode") from None
            return updated
        raise IncidentConflict("Incident was changed concurrently")

    def export_confirmed(self, start, end):
        try:
            hits = scan(self.client, index=self.index, ignore_unavailable=True, query={
                "query": {"bool": {"filter": [
                    {"term": {"status": "resolved"}},
                    {"term": {"disposition": "confirmed_incident"}},
                    {"range": {"window_from": {"gte": start.isoformat()}}},
                    {"range": {"window_to": {"lte": end.isoformat()}}},
                ]}},
            })
            labels = [{
                "incident_id": doc["episode_id"], "service": doc["service"],
                "window_from": doc["window_from"], "window_to": doc["window_to"],
                "expected_cluster_signature": doc["signature"], "description": doc["note"],
            } for doc in (hit["_source"] for hit in hits)]
        except Exception:
            raise StorageError("cannot export incident labels") from None
        return sorted(labels, key=lambda label: (utc_timestamp(label["window_from"]), label["incident_id"]))
