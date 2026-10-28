"""Cau hinh auth doc tu bien moi truong, tach khoi cau hinh ingestion."""

from __future__ import annotations

import os


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a positive integer") from None
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


# Khong co secret mac dinh. Auth phai goi require_jwt_secret() truoc khi dung.
JWT_SECRET = os.environ.get("JWT_SECRET")
JWT_EXPIRY_SECONDS = _positive_int("JWT_EXPIRY_SECONDS", 3600)
ADMIN_SEED_USERNAME = os.environ.get("ADMIN_SEED_USERNAME")
ADMIN_SEED_PASSWORD = os.environ.get("ADMIN_SEED_PASSWORD")
USERS_INDEX = os.environ.get("USERS_INDEX", "users")
if not USERS_INDEX.strip():
    raise ValueError("USERS_INDEX must not be empty")


def require_jwt_secret() -> str:
    """Tu choi auth neu thieu secret; khong anh huong cac route chua co auth."""
    if JWT_SECRET is None or not JWT_SECRET.strip():
        raise ValueError("JWT_SECRET must be set for authentication")
    return JWT_SECRET
