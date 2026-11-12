"""Small thread-safe test double with CAS; live tests independently verify OpenSearch semantics."""

from copy import deepcopy
from threading import RLock
from unittest.mock import Mock
from opensearchpy.exceptions import ConflictError, NotFoundError


def fake_client(documents=None, indexes=None):
    documents = {} if documents is None else documents
    indexes = set(indexes or (index for index, _ in documents))
    revisions = {key: 0 for key in documents}
    lock = RLock()
    client = Mock()
    client.ping.return_value = True
    client.indices.exists.side_effect = lambda *, index: index in indexes

    def create_index(*, index, body):
        indexes.add(index)
        return {"acknowledged": True}

    def get(*, index, id, **kwargs):
        with lock:
            if index not in indexes:
                raise NotFoundError(404, "index_not_found_exception")
            key = index, id
            if key not in documents:
                raise NotFoundError(404, "not_found")
            return {"found": True, "_id": id, "_source": deepcopy(documents[key]),
                    "_seq_no": revisions.get(key, 0), "_primary_term": 1}

    def create(*, index, id, body, **kwargs):
        with lock:
            key = index, id
            if key in documents:
                raise ConflictError(409, "version_conflict_engine_exception")
            indexes.add(index)
            documents[key] = deepcopy(body)
            revisions[key] = 0
            return {"result": "created"}

    def replace(*, index, id, body, if_seq_no=None, if_primary_term=None, **kwargs):
        with lock:
            key = index, id
            if if_seq_no is not None and revisions.get(key) != if_seq_no:
                raise ConflictError(409, "version_conflict_engine_exception")
            documents[key] = deepcopy(body)
            revisions[key] = revisions.get(key, -1) + 1
            return {"result": "updated"}

    def update(*, index, id, body, **kwargs):
        with lock:
            old = get(index=index, id=id)
            return replace(index=index, id=id, body={**old["_source"], **body["doc"]})

    client.indices.create.side_effect = create_index
    client.get.side_effect = get
    client.create.side_effect = create
    client.index.side_effect = replace
    client.update.side_effect = update
    return client, documents
