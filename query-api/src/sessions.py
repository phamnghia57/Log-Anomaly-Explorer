"""Persistent, compare-and-swap refresh rotation shared by every API instance."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from opensearchpy.exceptions import ConflictError, NotFoundError, RequestError
from ingestion.src.storage import OpenSearchLogStore, StorageError
from . import config
from .tokens import create_access_token, create_refresh_token, jwt_settings

SESSION_MAPPING = {"dynamic": "strict", "properties": {
    "username": {"type": "keyword"}, "auth_version": {"type": "keyword"},
    "refresh_hash": {"type": "keyword", "index": False, "doc_values": False},
    "created_at": {"type": "date"}, "expires_at": {"type": "date"},
    "revoked_at": {"type": "date"},
}}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def user_version(user: dict) -> str:
    value = user.get("auth_version", "legacy")
    if not isinstance(value, str) or not value.strip():
        raise jwt.InvalidTokenError("Invalid account version")
    return value


def active_admin(user: dict | None, username: str) -> bool:
    return bool(user and user.get("username") == username and user.get("role") == "admin"
                and user.get("enabled", True) is True)


class SessionRepository:
    def __init__(self, log_store):
        if not isinstance(log_store, OpenSearchLogStore):
            raise ValueError("Session storage requires OpenSearch")
        self.log_store, self.client = log_store, log_store.client
        self.index = config.AUTH_SESSIONS_INDEX

    def ensure_ready(self) -> None:
        try:
            if not self.client.indices.exists(index=self.index):
                result = self.client.indices.create(index=self.index, body={
                    "settings": self.log_store._settings(), "mappings": SESSION_MAPPING,
                })
                if not result.get("acknowledged"):
                    raise StorageError("session index creation was not acknowledged")
        except RequestError as exc:
            if exc.error != "resource_already_exists_exception":
                raise StorageError("cannot prepare session index") from None
        except Exception:
            raise StorageError("cannot prepare session index") from None

    def get_record(self, sid: str) -> dict | None:
        try:
            result = self.client.get(index=self.index, id=sid, realtime=True)
            return result if result.get("found") else None
        except NotFoundError as exc:
            if exc.error == "index_not_found_exception":
                raise StorageError("session index is missing") from None
            return None
        except Exception:
            raise StorageError("cannot read session") from None

    def _replace(self, sid: str, record: dict, source: dict) -> None:
        try:
            self.client.index(index=self.index, id=sid, body=source,
                              if_seq_no=record["_seq_no"], if_primary_term=record["_primary_term"])
        except ConflictError:
            raise
        except Exception:
            raise StorageError("cannot update session") from None

    def start(self, user: dict) -> tuple[dict, str, datetime]:
        jwt_settings()
        sid = secrets.token_urlsafe(32)
        version = user_version(user)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires = now + timedelta(seconds=config.AUTH_REFRESH_TTL_SECONDS)
        arguments = {"sid": sid, "auth_version": version, "session_expires_at": expires}
        access = create_access_token(user["username"], **arguments)
        refresh = create_refresh_token(user["username"], **arguments)
        try:
            if not self.client.indices.exists(index=self.index):
                raise StorageError("session storage must be initialized")
            self.client.create(index=self.index, id=sid, body={
                "username": user["username"], "auth_version": version,
                "refresh_hash": token_hash(refresh), "created_at": now.isoformat(),
                "expires_at": expires.isoformat(), "revoked_at": None,
            })
        except Exception:
            raise StorageError("cannot create session") from None
        return access, refresh, expires

    def validate(self, claims: dict, users) -> dict:
        record = self.get_record(claims["sid"])
        if not record:
            raise jwt.InvalidTokenError("Invalid session")
        source = record["_source"]
        try:
            expires_at = datetime.fromisoformat(source["expires_at"])
            if expires_at.tzinfo is None or not isinstance(source["refresh_hash"], str):
                raise ValueError("Invalid session record")
        except (KeyError, TypeError, ValueError):
            raise StorageError("invalid session record") from None
        if (source.get("username") != claims["sub"]
                or source.get("auth_version") != claims["ver"] or source.get("revoked_at")
                or expires_at <= datetime.now(timezone.utc)):
            raise jwt.InvalidTokenError("Invalid session")
        user = users.get(claims["sub"])
        if not active_admin(user, claims["sub"]) or user_version(user) != claims["ver"]:
            raise jwt.InvalidTokenError("Invalid account")
        return record

    def refresh(self, token: str, claims: dict, users) -> tuple[dict, str, datetime]:
        for _ in range(4):
            record = self.validate(claims, users)
            source = record["_source"]
            if not hmac.compare_digest(source["refresh_hash"], token_hash(token)):
                # Only a signed refresh JWT reaches here. Random input cannot revoke a session.
                self.revoke(claims["sid"])
                raise jwt.InvalidTokenError("Refresh token reused")
            expires = datetime.fromisoformat(source["expires_at"])
            arguments = {"sid": claims["sid"], "auth_version": claims["ver"], "session_expires_at": expires}
            replacement = create_refresh_token(claims["sub"], **arguments)
            access = create_access_token(claims["sub"], **arguments)
            try:
                self._replace(claims["sid"], record, {**source, "refresh_hash": token_hash(replacement)})
                return access, replacement, expires
            except ConflictError:
                continue  # Re-read; never overwrite a concurrent revoke or rotation.
        raise StorageError("session update contention")

    def revoke(self, sid: str) -> None:
        for _ in range(8):
            record = self.get_record(sid)
            if not record or record["_source"].get("revoked_at"):
                return
            try:
                self._replace(sid, record, {**record["_source"],
                              "revoked_at": datetime.now(timezone.utc).isoformat()})
                return
            except ConflictError:
                continue
        raise StorageError("session update contention")

    def cleanup(self) -> None:
        try:
            self.client.delete_by_query(index=self.index, body={"query": {"range": {
                "expires_at": {"lte": datetime.now(timezone.utc).isoformat()}
            }}}, conflicts="proceed")
        except Exception:
            raise StorageError("cannot clean expired sessions") from None
