import importlib
import os
import secrets
import sys
from pathlib import Path

import pytest

# Backend nhe, khong can OpenSearch that. Phai set TRUOC khi import main vi
# store = build_store() chay ngay luc import module.
os.environ.setdefault("STORAGE_BACKEND", "memory")

# Them GOC REPO (khong phai thu muc query-api) vao sys.path: query-api import
# thang `ingestion.src.storage`, va test import `query-api.src.main` bang ten
# day du de khong dung ten package "src" voi cac module khac khi chay chung.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def admin_auth(monkeypatch):
    """JWT that cho API regression tests; khong bypass authentication dependency."""
    config = importlib.import_module("query-api.src.config")
    main = importlib.import_module("query-api.src.main")
    users = importlib.import_module("query-api.src.users")
    sessions = importlib.import_module("query-api.src.sessions")
    fake = importlib.import_module("query-api.tests.fake_opensearch")
    from ingestion.src.storage import OpenSearchLogStore
    monkeypatch.setattr(config, "JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setattr(config, "JWT_EXPIRY_SECONDS", 3600)
    monkeypatch.setattr(config, "AUTH_SESSIONS_INDEX", "unit-auth-sessions")
    client, _ = fake.fake_client({(config.USERS_INDEX, "test-admin"): {
        "username": "test-admin", "role": "admin", "auth_version": "unit-version",
    }})
    store = OpenSearchLogStore(client)
    repository = sessions.SessionRepository(store)
    repository.ensure_ready()
    monkeypatch.setattr(main.app.state, "user_repository", users.UserRepository(store), raising=False)
    monkeypatch.setattr(main.app.state, "session_repository", repository, raising=False)
    access, _, _ = repository.start({"username": "test-admin", "role": "admin", "auth_version": "unit-version"})
    return {"Authorization": f"Bearer {access['token']}"}
