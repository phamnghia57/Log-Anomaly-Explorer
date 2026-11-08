"""One versioned conversation per cluster, with one atomic Undo snapshot."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from jsonschema import Draft7Validator, FormatChecker
from opensearchpy.exceptions import ConflictError, NotFoundError, RequestError

from ingestion.src.storage import OpenSearchLogStore, StorageError, build_store

from . import config

_MAX_VERSION = 2**63 - 1
_REVISION = re.compile(r"([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})", re.ASCII)
_SCHEMA = Path(__file__).resolve().parents[3] / "docs/architect/contracts/assistant-conversation-schema.json"
_VALIDATOR = Draft7Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")),
                             format_checker=FormatChecker())

UNDO_MAPPING = {"type": "object", "enabled": False}
CONVERSATION_MAPPING = {
    "dynamic": "strict",
    "properties": {
        "cluster_id": {"type": "keyword"},
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
        "messages": {"type": "object", "dynamic": False},
        "undo": UNDO_MAPPING,
    },
}


def parse_revision(value: str) -> tuple[int, int]:
    """Validate canonical primary-term:sequence-number, including sequence zero."""
    match = _REVISION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("Invalid conversation revision")
    term, sequence = map(int, match.groups())
    if term > _MAX_VERSION or sequence > _MAX_VERSION:
        raise ValueError("Invalid conversation revision")
    return term, sequence


class ConversationConflict(Exception):
    def __init__(self, reason: str = "revision_conflict"):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ConversationState:
    document: dict
    seq_no: int
    primary_term: int

    @property
    def revision(self) -> str:
        return f"{self.primary_term}:{self.seq_no}"


def _state(cluster_id: str, document: dict, metadata: dict) -> ConversationState:
    try:
        _VALIDATOR.validate(document)
        if document["cluster_id"] != cluster_id:
            raise ValueError("Conversation identity mismatch")
        sequence, term = metadata["_seq_no"], metadata["_primary_term"]
        if type(sequence) is not int or type(term) is not int:
            raise ValueError("Invalid version metadata")
        parse_revision(f"{term}:{sequence}")
        return ConversationState(deepcopy(document), sequence, term)
    except Exception:
        raise StorageError("invalid conversation data or version metadata") from None


class ConversationRepository:
    def __init__(self, log_store=None):
        self.log_store = log_store if log_store is not None else build_store()
        if not isinstance(self.log_store, OpenSearchLogStore):
            raise ValueError("Assistant conversation storage requires STORAGE_BACKEND=opensearch")
        self.client = self.log_store.client
        self.index = config.CONVERSATIONS_INDEX

    def ensure_ready(self) -> None:
        """Create a new index or add the optional field to an existing strict map."""
        try:
            if not self.client.indices.exists(index=self.index):
                try:
                    result = self.client.indices.create(index=self.index, body={
                        "settings": self.log_store._settings(),
                        "mappings": CONVERSATION_MAPPING,
                    })
                except RequestError as exc:
                    if exc.error != "resource_already_exists_exception":
                        raise
                    # Another worker created the index; still ensure its mapping.
                else:
                    if not result.get("acknowledged"):
                        raise StorageError("conversation index creation was not acknowledged")
                    return
            result = self.client.indices.put_mapping(index=self.index, body={
                "properties": {"undo": UNDO_MAPPING},
            })
            if not result.get("acknowledged"):
                raise StorageError("conversation mapping update was not acknowledged")
        except Exception:
            raise StorageError("cannot prepare conversation storage") from None

    def get(self, cluster_id: str) -> ConversationState | None:
        """Only a genuine absent document means no conversation, never an index error."""
        try:
            response = self.client.get(index=self.index, id=cluster_id)
            if response.get("found") is False and "error" not in response:
                return None
            if response.get("found") is not True:
                raise StorageError("invalid conversation response")
            return _state(cluster_id, response["_source"], response)
        except NotFoundError as exc:
            if (exc.error != "index_not_found_exception" and isinstance(exc.info, dict)
                    and exc.info.get("found") is False and "error" not in exc.info):
                return None
            raise StorageError("conversation storage is unavailable") from None
        except Exception:
            raise StorageError("cannot read conversation") from None

    def _write(self, cluster_id: str, document: dict,
               previous: ConversationState | None) -> ConversationState:
        # Validate before any I/O. Version metadata is never stored in _source.
        try:
            _VALIDATOR.validate(document)
        except Exception:
            raise StorageError("invalid conversation data") from None
        body = deepcopy(document)
        try:
            if previous is None:
                response = self.client.create(index=self.index, id=cluster_id,
                                              body=body, refresh="wait_for")
            else:
                response = self.client.index(
                    index=self.index, id=cluster_id, body=body, refresh="wait_for",
                    if_seq_no=previous.seq_no, if_primary_term=previous.primary_term,
                )
        except ConflictError:
            raise ConversationConflict() from None
        except Exception:
            raise StorageError("cannot save conversation") from None
        # A malformed write response has an uncertain outcome. Never fabricate
        # version metadata or retry the write; the caller must reconcile by GET.
        return _state(cluster_id, body, response)

    def save(self, cluster_id: str, messages: list[dict], *,
             previous: ConversationState | None) -> ConversationState:
        """Commit a completed Send and its previous history in the same document."""
        now = datetime.now(timezone.utc).isoformat()
        document = {
            "cluster_id": cluster_id,
            "created_at": previous.document["created_at"] if previous else now,
            "updated_at": now,
            "messages": deepcopy(messages),
            "undo": {"messages": deepcopy(previous.document["messages"]) if previous else []},
        }
        return self._write(cluster_id, document, previous)

    def undo(self, cluster_id: str, expected_revision: str) -> ConversationState:
        parse_revision(expected_revision)
        current = self.get(cluster_id)
        if current is None or current.revision != expected_revision:
            raise ConversationConflict()
        snapshot = current.document.get("undo")
        if snapshot is None:
            raise ConversationConflict("nothing_to_undo")
        document = deepcopy(current.document)
        document.update(messages=deepcopy(snapshot["messages"]), undo=None,
                        updated_at=datetime.now(timezone.utc).isoformat())
        return self._write(cluster_id, document, current)

    def close(self) -> None:
        self.client.close()
