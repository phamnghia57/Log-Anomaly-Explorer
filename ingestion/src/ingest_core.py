"""
Logic xu ly ingest KHONG phu thuoc FastAPI (tach tu main.py, khong doi hanh vi).

Muc dich: test duoc o muc service (status + body) ma khong can khoi dong
web framework; main.py chi con la lop map Result -> HTTP response.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .idempotency import (REPLAY_HEADER, IdempotencyStore, derive_log_id, fingerprint,
                          validate_key)
from .storage import LogStore
from .validator import validate_log


@dataclass
class Result:
    """Ket qua mot request ingest, doc lap voi framework HTTP."""

    status: int
    body: dict
    headers: dict = field(default_factory=dict)


def new_log_id(_index: int = 0) -> str:
    return str(uuid.uuid4())


def process_single(store: LogStore, payload: dict,
                   log_id_for: Callable[[int], str] = new_log_id) -> Result:
    errors = validate_log(payload)
    if errors:
        store.write_quarantine(payload, errors)
        # api-contract.md: log sai schema -> 400, vao quarantine, khong vao index chinh
        return Result(400, {"accepted": False, "reason": "schema_validation_failed",
                            "details": errors})
    log_id = log_id_for(0)
    store.write_log(log_id, payload)
    return Result(202, {"accepted": True, "log_id": log_id})


def process_batch(store: LogStore, payload: list[dict], max_batch_size: int,
                  log_id_for: Callable[[int], str] = new_log_id) -> Result:
    """Validate TOAN BO truoc khi ghi; invalid -> quarantine, khong ghi item nao."""
    if not payload or len(payload) > max_batch_size:
        return Result(400, {"detail": f"batch must contain 1..{max_batch_size} logs"})
    invalid = [{"index": i, "details": errors} for i, item in enumerate(payload)
               if (errors := validate_log(item))]
    if invalid:
        for entry in invalid:
            store.write_quarantine(payload[entry["index"]], entry["details"])
        return Result(400, {"accepted": False, "reason": "schema_validation_failed",
                            "errors": invalid})
    items = [(log_id_for(i), log) for i, log in enumerate(payload)]
    store.write_logs_batch(items)
    return Result(202, {"accepted": True, "accepted_count": len(items),
                        "log_ids": [log_id for log_id, _ in items]})


# --------------------------------------------------------------------------- VT-014 idempotency
def _idempotent(idem: IdempotencyStore, key: str, endpoint: str, payload: Any,
                run: Callable[[Callable[[int], str]], Result]) -> Result:
    """Bat bien: moi key con hieu luc -> toi da 1 lan xu ly thanh cong; moi lan gui lai
    cung payload nhan dung status + body lan dau."""
    error = validate_key(key)
    if error:
        return Result(400, {"accepted": False, "reason": "invalid_idempotency_key",
                            "details": error})
    fp = fingerprint(endpoint, payload)
    with idem.locked(key):
        previous = idem.get(key)
        if previous is not None:
            if previous.fingerprint != fp:
                return Result(409, {"accepted": False, "reason": "idempotency_key_reused",
                                    "details": "Idempotency-Key da dung cho mot yeu cau khac"})
            return Result(previous.status, previous.body, {REPLAY_HEADER: "true"})
        result = run(lambda index: derive_log_id(key, fp, index))
        # StorageError (5xx) duoc nem ra truoc khi toi day -> khong luu, client retry duoc.
        if result.status < 500:
            idem.save(key, fp, result.status, result.body)
        return result


def handle_ingest(store: LogStore, idem: IdempotencyStore, payload: dict,
                  key: str | None) -> Result:
    if key is None:
        return process_single(store, payload)
    return _idempotent(idem, key, "/ingest", payload,
                       lambda id_for: process_single(store, payload, id_for))


def handle_ingest_batch(store: LogStore, idem: IdempotencyStore, payload: list[dict],
                        key: str | None, max_batch_size: int) -> Result:
    if key is None:
        return process_batch(store, payload, max_batch_size)
    return _idempotent(idem, key, "/ingest/batch", payload,
                       lambda id_for: process_batch(store, payload, max_batch_size, id_for))
