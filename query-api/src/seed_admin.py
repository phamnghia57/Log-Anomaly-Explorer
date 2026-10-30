"""Seed admin tu repo root: python -m query-api.src.seed_admin."""

import sys

from argon2.exceptions import HashingError

from ingestion.src.storage import StorageError

from . import config
from .users import UserRepository


def seed_admin(repository: UserRepository | None = None) -> bool:
    # Validate truoc khi mo ket noi hay tao index. Seed khong phat JWT nen khong can secret.
    username, password = config.require_admin_seed_credentials()
    owns_repository = repository is None
    repository = repository if repository is not None else UserRepository()
    try:
        repository.ensure_ready()
        if repository.get(username) is not None:
            return False
        return repository.create_admin(username, password)
    finally:
        if owns_repository:
            repository.close()


def main() -> int:
    try:
        created = seed_admin()
    except (ValueError, StorageError, HashingError):
        print(
            "Admin seeding failed; check ADMIN_SEED_USERNAME, ADMIN_SEED_PASSWORD "
            "and OpenSearch configuration/connectivity.",
            file=sys.stderr,
        )
        return 1
    print("Admin created." if created else "Existing account preserved; no changes made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
