"""
Idempotency cho POST /ingest va /ingest/batch (VT-014).

Client gui header `Idempotency-Key` (1..128 ky tu [A-Za-z0-9._:-]). Cung key + cung
payload -> tra lai DUNG response lan dau, khong ghi them. Cung key + payload khac -> 409.
Khong co header -> hanh vi cu (tuong thich nguoc). KHONG doi log-schema.json/LOG_MAPPING.

Hai lop bao ve:
  1. Cache trong process (`IdempotencyStore`, TTL) + khoa theo key -> request trung
     dong thoi cho nhau, chi 1 request thuc su ghi.
  2. log_id TAT DINH = uuid5(key, fingerprint, index): neu cache mat (restart, het TTL,
     nhieu replica) thi lan ghi lai van dung cung _id -> OpenSearch ghi de, khong trung.

Gioi han (giong SlidingWindowRateLimiter): cache la cua MOT process; nhieu worker/replica
chi con duoc bao ve boi lop 2 (khong co replay header, nhung khong trung document).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Iterator

KEY_PATTERN = re.compile(r"[A-Za-z0-9._:\-]{1,128}")
REPLAY_HEADER = "Idempotent-Replayed"
_NAMESPACE = uuid.UUID("6f1c2a5e-9d0b-4c47-8a51-0e7b2f3d4c60")  # co dinh cho log_id tat dinh


def validate_key(key: str) -> str | None:
    """None = hop le; nguoc lai tra thong diep loi."""
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        return "Idempotency-Key phai dai 1..128 ky tu, chi gom [A-Za-z0-9._:-]"
    return None


def fingerprint(endpoint: str, payload: Any) -> str:
    """Bam noi dung chuan hoa (sort_keys) + endpoint: thu tu field JSON khong anh huong."""
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, default=str)
    return hashlib.sha256(f"{endpoint}\n{canon}".encode("utf-8")).hexdigest()


def derive_log_id(key: str, fp: str, index: int = 0) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{key}|{fp}|{index}"))


@dataclass(frozen=True)
class StoredResponse:
    fingerprint: str
    status: int
    body: dict
    expires_at: float


class _KeyLock:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = Lock()
        self.users = 0


class IdempotencyStore:
    """Luu response da hoan tat theo key, TTL tinh bang `clock` (inject duoc khi test)."""

    def __init__(self, ttl_seconds: float = 86400,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        # dict giu thu tu chen; TTL nhu nhau -> thu tu chen = thu tu het han
        self._records: dict[str, StoredResponse] = {}
        self._key_locks: dict[str, _KeyLock] = {}
        self._lock = Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def _purge_expired_locked(self, now: float) -> None:
        while self._records:
            oldest_key = next(iter(self._records))
            if self._records[oldest_key].expires_at > now:
                break
            del self._records[oldest_key]

    @contextmanager
    def locked(self, key: str) -> Iterator[None]:
        """Serialize cac request cung key; khoa duoc don khi khong con ai dung."""
        with self._lock:
            self._purge_expired_locked(self.clock())
            key_lock = self._key_locks.setdefault(key, _KeyLock())
            key_lock.users += 1
        try:
            with key_lock.lock:
                yield
        finally:
            with self._lock:
                key_lock.users -= 1
                if key_lock.users == 0:
                    del self._key_locks[key]

    def get(self, key: str) -> StoredResponse | None:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            if record.expires_at <= self.clock():
                del self._records[key]
                return None
            return StoredResponse(record.fingerprint, record.status,
                                  copy.deepcopy(record.body), record.expires_at)

    def save(self, key: str, fp: str, status: int, body: dict) -> None:
        with self._lock:
            self._records.pop(key, None)  # chen lai cuoi -> giu thu tu het han
            self._records[key] = StoredResponse(fp, status, copy.deepcopy(body),
                                                self.clock() + self.ttl_seconds)
