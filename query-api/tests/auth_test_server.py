"""Loopback-only API for browser integration tests; OpenSearch is mocked.

Run explicitly via the dedicated Playwright config, never in production.
"""

import importlib
import os

import uvicorn

from .auth_stack import auth_stack


def main():
    required = ("AUTH_E2E_USERNAME", "AUTH_E2E_PASSWORD", "AUTH_E2E_SECRET")
    if not all(os.environ.get(name) for name in required):
        raise SystemExit("Dedicated auth test environment is required.")
    with auth_stack(username=os.environ[required[0]], password=os.environ[required[1]],
                    secret=os.environ[required[2]]) as stack:
        seed = importlib.import_module("query-api.src.seed_admin")
        # Do not put seeding side effects in assert (Python -O would skip them).
        if seed.main() != 0 or seed.main() != 0:
            raise SystemExit("Test admin seeding failed.")
        uvicorn.run(stack.app, host="127.0.0.1", port=8023, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
