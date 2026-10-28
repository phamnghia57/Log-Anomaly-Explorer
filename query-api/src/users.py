"""Admin repository dung client OpenSearch da cau hinh cua ingestion."""

from datetime import datetime, timezone

from opensearchpy.exceptions import ConflictError, NotFoundError, RequestError

from ingestion.src.storage import OpenSearchLogStore, StorageError, build_store

from . import config
from .passwords import hash_password

USER_MAPPING = {
    "dynamic": "strict",
    "properties": {
        "username": {"type": "keyword"},
        "password_hash": {"type": "keyword", "index": False, "doc_values": False},
        "role": {"type": "keyword"},
        "created_at": {"type": "date"},
        "last_login_at": {"type": "date"},
    },
}


class UserRepository:
    def __init__(self, log_store=None):
        try:
            self.log_store = log_store if log_store is not None else build_store()
        except Exception:
            raise StorageError("cannot connect to users storage") from None
        if not isinstance(self.log_store, OpenSearchLogStore):
            raise ValueError("Admin storage requires STORAGE_BACKEND=opensearch")
        self.client = self.log_store.client
        self.index = config.USERS_INDEX

    def ensure_ready(self) -> None:
        # Chi tao users, khong goi log_store.ensure_ready() de tao index log/quarantine.
        try:
            if not self.client.indices.exists(index=self.index):
                result = self.client.indices.create(index=self.index, body={
                    "settings": self.log_store._settings(), "mappings": USER_MAPPING,
                })
                if not result.get("acknowledged"):
                    raise StorageError("users index creation was not acknowledged")
        except RequestError as exc:
            # Hai seed process cung tao index: chi bo qua loi index da ton tai.
            if exc.error != "resource_already_exists_exception":
                raise StorageError("cannot prepare users index") from None
        except Exception:
            raise StorageError("cannot prepare users index") from None

    def get(self, username: str) -> dict | None:
        try:
            result = self.client.get(index=self.index, id=username)
            return result["_source"] if result.get("found") else None
        except NotFoundError as exc:
            if exc.error == "index_not_found_exception":
                raise StorageError("users index is missing") from None
            return None
        except Exception:
            raise StorageError("cannot read admin user") from None

    def create_admin(self, username: str, password: str) -> bool:
        """Create-only theo username; False neu account da duoc process khac tao."""
        if not username or not username.strip():
            raise ValueError("Username must not be empty")
        document = {
            "username": username,
            "password_hash": hash_password(password),
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # _create la atomic; khong dung index/upsert de tranh doi password co san.
            self.client.create(index=self.index, id=username, body=document, refresh="wait_for")
            return True
        except ConflictError:
            return False
        except Exception:
            # Khong de response/body/connection credentials lot vao log hay traceback.
            raise StorageError("cannot create admin user") from None

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            raise StorageError("cannot close users storage") from None
