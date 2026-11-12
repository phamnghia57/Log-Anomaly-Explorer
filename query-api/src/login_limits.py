"""Shared per-account login budget. Reserve each attempt before hashing."""

import hashlib
import hmac
import math
import time
from uuid import uuid4

from opensearchpy.exceptions import ConflictError, NotFoundError, RequestError

from ingestion.src.storage import StorageError
from . import config


class LoginLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


class LoginLimiter:
    def __init__(self, store):
        self.store, self.client = store, store.client
        self.index = config.AUTH_LOGIN_LIMIT_INDEX

    def ensure_ready(self):
        try:
            if not self.client.indices.exists(index=self.index):
                result = self.client.indices.create(index=self.index, body={
                    "settings": self.store._settings(),
                    "mappings": {"dynamic": "strict", "properties": {
                        "attempts": {"type": "integer"}, "expires_at": {"type": "date"},
                        "window_id": {"type": "keyword", "index": False},
                    }},
                })
                if not result.get("acknowledged"):
                    raise StorageError("login limiter index creation was not acknowledged")
        except RequestError as exc:
            if exc.error != "resource_already_exists_exception":
                raise StorageError("cannot prepare login limiter") from None
        except Exception:
            raise StorageError("cannot prepare login limiter") from None

    def _get(self, key):
        try:
            return self.client.get(index=self.index, id=key, realtime=True)
        except NotFoundError as exc:
            if exc.error == "index_not_found_exception":
                raise StorageError("login limiter index is missing") from None
            return None
        except Exception:
            raise StorageError("cannot read login budget") from None

    def reserve(self, username):
        key = hmac.new(config.require_jwt_secret().encode(), b"login-limit:" + username.encode(),
                       hashlib.sha256).hexdigest()
        for _ in range(12):
            record = self._get(key)
            now = time.time_ns() // 1_000_000
            source = record["_source"] if record else None
            if source is None or source["expires_at"] <= now:
                attempts, expires_at = 1, now + config.AUTH_LOGIN_WINDOW_SECONDS * 1000
                window_id = uuid4().hex
            else:
                if source["attempts"] >= config.AUTH_LOGIN_MAX_ATTEMPTS:
                    raise LoginLimited(max(1, math.ceil((source["expires_at"] - now) / 1000)))
                attempts, expires_at = source["attempts"] + 1, source["expires_at"]
                window_id = source["window_id"]
            if attempts == config.AUTH_LOGIN_MAX_ATTEMPTS:
                expires_at = now + config.AUTH_LOGIN_LOCK_SECONDS * 1000

            budget = {"attempts": attempts, "expires_at": expires_at, "window_id": window_id}
            try:
                if record is None:
                    self.client.create(index=self.index, id=key, body=budget)
                else:
                    self.client.index(index=self.index, id=key, body=budget,
                                      if_seq_no=record["_seq_no"], if_primary_term=record["_primary_term"])
            except ConflictError:
                continue
            except Exception:
                raise StorageError("cannot reserve login attempt") from None
            return key, window_id
        raise StorageError("login budget contention")

    def reset(self, reservation):
        key, window_id = reservation
        for _ in range(12):
            record = self._get(key)
            if record is None or record["_source"]["window_id"] != window_id:
                return
            try:
                self.client.index(index=self.index, id=key, body={**record["_source"], "expires_at": 0},
                                  if_seq_no=record["_seq_no"], if_primary_term=record["_primary_term"])
            except ConflictError:
                continue
            except Exception:
                raise StorageError("cannot reset login budget") from None
            return
        raise StorageError("login budget contention")

    def cleanup(self):
        try:
            self.client.delete_by_query(index=self.index, conflicts="proceed", ignore=[404], body={
                "query": {"range": {"expires_at": {"lte": time.time_ns() // 1_000_000}}},
            })
        except Exception:
            raise StorageError("cannot clean up login budgets") from None
