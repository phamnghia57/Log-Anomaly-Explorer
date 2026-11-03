"""Create-only approvals, isolated from original logs, clusters and history."""

from opensearchpy.exceptions import ConflictError, NotFoundError

from ingestion.src.storage import StorageError


class ApprovalRepository:
    def __init__(self, log_store):
        self.client = log_store.client
        self.index = "cluster-approvals"

    def create(self, document: dict) -> bool:
        try:
            # A deterministic ID and _create arbitrate competing processes in storage.
            result = self.client.create(
                index=self.index, id=document["cluster_id"], body=document,
                refresh="wait_for",
            )
            if result.get("result") != "created":
                raise StorageError("approval creation was not confirmed")
            return True
        except ConflictError:
            return False
        except Exception:
            raise StorageError("cannot create approval") from None

    def get(self, cluster_id: str) -> dict | None:
        try:
            result = self.client.get(index=self.index, id=cluster_id)
            return result["_source"] if result.get("found") else None
        except NotFoundError as exc:
            if exc.error == "index_not_found_exception":
                raise StorageError("approval index is missing") from None
            return None
        except Exception:
            raise StorageError("cannot read approval") from None
