"""Explicit operator actions: python -m query-api.src.manage_auth --help."""

import argparse
import getpass
import sys
from argon2.exceptions import HashingError
from ingestion.src.storage import StorageError
from .sessions import SessionRepository
from .users import UserRepository


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Initialize auth storage or administer accounts")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("init", help="Migrate users mapping and create session index idempotently")
    for action in ("disable", "enable", "set-password", "set-role", "revoke-all"):
        command = sub.add_parser(action)
        command.add_argument("username")
        if action == "set-role":
            command.add_argument("role", choices=("admin", "viewer"))
    args = parser.parse_args(argv)
    repository = None
    try:
        repository = UserRepository()
        if args.action == "init":
            repository.ensure_ready()
            SessionRepository(repository.log_store).ensure_ready()
        else:
            value = getattr(args, "role", None)
            if args.action == "set-password":
                value = getpass.getpass("New password: ")
                if value != getpass.getpass("Confirm password: "):
                    raise ValueError("Passwords do not match")
            repository.administer(args.username, args.action, value=value)
    except (ValueError, StorageError, HashingError, EOFError):
        print("Auth administration failed; check account, input and storage.", file=sys.stderr)
        return 1
    finally:
        if repository is not None:
            repository.close()
    print("Auth administration completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
