"""Small OpenSearch document-protocol double, with no Assistant business logic.

Unconditional writes deliberately overwrite. Only explicit create/CAS arguments
can cause a conflict, so the fake cannot supply missing production protection.
"""

from copy import deepcopy
from threading import RLock

from opensearchpy.exceptions import ConflictError, NotFoundError, RequestError


class FakeIndices:
    def __init__(self, owner):
        self.owner = owner

    def exists(self, *, index):
        with self.owner.lock:
            return index in self.owner.mappings

    def create(self, *, index, body):
        with self.owner.lock:
            if index in self.owner.mappings:
                raise RequestError(400, "resource_already_exists_exception", {})
            self.owner.mappings[index] = deepcopy(body)
            return {"acknowledged": True}

    def delete(self, *, index):
        with self.owner.lock:
            self.owner.mappings.pop(index)
            self.owner.documents = {
                key: value for key, value in self.owner.documents.items()
                if key[0] != index
            }
            self.owner.next_sequence.pop(index, None)
            return {"acknowledged": True}

    def put_mapping(self, *, index, body):
        with self.owner.lock:
            if index not in self.owner.mappings:
                raise NotFoundError(404, "index_not_found_exception", {})
            mapping = self.owner.mappings[index].setdefault("mappings", {})
            mapping.setdefault("properties", {}).update(deepcopy(body["properties"]))
            return {"acknowledged": True}


class RevisionedOpenSearch:
    def __init__(self):
        self.lock = RLock()
        self.mappings = {}
        self.documents = {}
        self.next_sequence = {}
        self.write_attempts = []
        self.commits = []
        self.read_error = None
        self.indices = FakeIndices(self)

    @staticmethod
    def _not_found(index, document_id, *, missing_index, ignore):
        kind = "index_not_found_exception" if missing_index else "not_found"
        body = {"error": {"type": kind}, "status": 404} if missing_index else {
            "_index": index, "_id": document_id, "found": False,
        }
        ignored = (ignore,) if isinstance(ignore, int) else (ignore or ())
        if 404 in ignored:
            return deepcopy(body)
        raise NotFoundError(404, kind, deepcopy(body))

    def get(self, *, index, id, ignore=None):
        with self.lock:
            if self.read_error is not None:
                raise self.read_error
            if index not in self.mappings:
                return self._not_found(index, id, missing_index=True, ignore=ignore)
            document = self.documents.get((index, id))
            if document is None:
                return self._not_found(index, id, missing_index=False, ignore=ignore)
            return deepcopy(document)

    def index(self, *, index, id, body, refresh=False, op_type="index",
              if_seq_no=None, if_primary_term=None):
        with self.lock:
            self.write_attempts.append({
                "index": index, "id": id, "body": deepcopy(body),
                "op_type": op_type, "if_seq_no": if_seq_no,
                "if_primary_term": if_primary_term,
            })
            current = self.documents.get((index, id))
            conditional = if_seq_no is not None or if_primary_term is not None
            if conditional and (if_seq_no is None or if_primary_term is None):
                raise RequestError(400, "both sequence number and primary term required", {})
            conflict = op_type == "create" and current is not None
            if conditional:
                conflict = conflict or current is None or (
                    current["_seq_no"], current["_primary_term"]
                ) != (if_seq_no, if_primary_term)
            if conflict:
                raise ConflictError(409, "version_conflict_engine_exception", {})
            # OpenSearch normally auto-creates a missing index on an index write.
            self.mappings.setdefault(index, {})
            sequence = self.next_sequence.get(index, 0)
            self.next_sequence[index] = sequence + 1
            document = {
                "_index": index, "_id": id, "found": True,
                "_seq_no": sequence, "_primary_term": 1,
                "_version": (current["_version"] + 1) if current else 1,
                "_source": deepcopy(body),
            }
            self.documents[(index, id)] = document
            self.commits.append(deepcopy(document))
            return {
                key: deepcopy(value) for key, value in document.items()
                if key not in {"found", "_source"}
            } | {"result": "updated" if current else "created"}

    def create(self, *, index, id, body, refresh=False):
        return self.index(index=index, id=id, body=body, refresh=refresh,
                          op_type="create")

    def snapshot(self, *, index, id):
        """Independent storage oracle; does not use the injected read failure."""
        with self.lock:
            return deepcopy(self.documents.get((index, id)))

    def clear_activity(self):
        with self.lock:
            self.write_attempts.clear()
            self.commits.clear()
