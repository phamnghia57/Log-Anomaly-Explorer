"""Test-only real API process and deterministic generation/synchronization.

No auth overrides and no persistence fake. All storage calls use opensearch-py.
This module is launched only by the opt-in VT-013 integration tests.
"""

from importlib import import_module
import json
import os
from pathlib import Path
from threading import Barrier, Lock

TIMESTAMP = "2026-11-08T00:00:00+00:00"
CLUSTER = "vt013-integration-cluster"


def turn(message):
    return [
        {"role": "user", "content": message, "created_at": TIMESTAMP},
        {"role": "assistant", "content": "Deterministic integration answer.",
         "created_at": TIMESTAMP},
    ]


def serve():
    import sys
    import uvicorn
    from opensearchpy import OpenSearch

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main = import_module("query-api.src.main")
    router = import_module("query-api.src.assistant.router")
    assert main.app.state.assistant_conversations is not None, "Real repository startup failed"
    main.cluster_store.ensure_ready()
    users = main.app.state.user_repository
    users.ensure_ready()
    users.create_admin(os.environ["ADMIN_SEED_USERNAME"], os.environ["ADMIN_SEED_PASSWORD"])

    mode = os.environ["VT013_SERVER_MODE"]
    barrier = Barrier(2, timeout=20)
    event_lock = Lock()
    events = Path(os.environ["VT013_SERVER_EVENTS"])

    def generate(**kwargs):
        with event_lock, events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"generation": kwargs["user_message"]}) + "\n")
        # Both requests have already read the same real persisted version.
        if mode == "concurrent-send":
            barrier.wait()
        return turn(kwargs["user_message"])

    router.run_chat_turn = generate
    repository = main.app.state.assistant_conversations
    if mode == "concurrent-undo":
        real_get = repository.client.get
        count = 0
        lock = Lock()

        def synchronized_get(*args, **kwargs):
            nonlocal count
            response = real_get(*args, **kwargs)
            should_wait = False
            if kwargs.get("index") == repository.index:
                with lock:
                    count += 1
                    should_wait = count <= 2
            if should_wait:
                barrier.wait()
            return response

        # Synchronization after the real read, not a synthesized response.
        repository.client.get = synchronized_get
    elif mode == "missing-index":
        repository.index = os.environ["VT013_MISSING_INDEX"]
    elif mode == "read-failure":
        # A real SDK connection failure; other repositories remain connected.
        repository.client = OpenSearch(
            hosts=[os.environ["VT013_UNREACHABLE_URL"]], timeout=1,
            max_retries=0, retry_on_timeout=False,
        )

    uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ["VT013_API_PORT"]),
                log_level="warning", access_log=False)


if __name__ == "__main__":
    serve()
