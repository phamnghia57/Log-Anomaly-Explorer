"""Explicit reviewer and approval-index setup: python -m query-api.src.setup_reviewer."""
import os
import sys

from argon2.exceptions import HashingError

from ingestion.src.storage import StorageError, build_store

from .approvals import ApprovalRepository
from .users import UserRepository


def setup_reviewer(log_store=None) -> bool:
    username = os.environ.get("REVIEWER_SEED_USERNAME", "")
    password = os.environ.get("REVIEWER_SEED_PASSWORD", "")
    if not username.strip() or not password.strip():
        raise ValueError("Reviewer seed credentials must be set")
    owns_store = log_store is None
    if owns_store:
        try:
            log_store = build_store()
        except Exception:
            raise StorageError("cannot connect to reviewer storage") from None
    users = UserRepository(log_store)
    try:
        users.ensure_ready()
        ApprovalRepository(log_store).ensure_ready()
        if users.get(username) is not None:
            return False
        return users.create_reviewer(username, password)
    finally:
        if owns_store:
            users.close()


def main() -> int:
    try:
        created = setup_reviewer()
    except (ValueError, StorageError, HashingError):
        print("Reviewer setup failed; check REVIEWER_SEED_USERNAME, "
              "REVIEWER_SEED_PASSWORD and OpenSearch configuration/connectivity.", file=sys.stderr)
        return 1
    print("Reviewer created; approval storage prepared." if created else
          "Approval storage prepared; existing account preserved (role/password unchanged).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
