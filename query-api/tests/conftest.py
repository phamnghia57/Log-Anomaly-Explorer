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
    tokens = importlib.import_module("query-api.src.tokens")
    monkeypatch.setattr(config, "JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setattr(config, "JWT_EXPIRY_SECONDS", 3600)
    return {"Authorization": f"Bearer {tokens.create_access_token('test-admin')['token']}"}
