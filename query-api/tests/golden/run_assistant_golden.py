from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import time
from datetime import datetime, timezone

import httpx

BASE_URL = os.environ.get("QUERY_API_HOST", "http://query-api:8002")
OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")
CONVERSATIONS_INDEX = os.environ.get("ASSISTANT_CONVERSATIONS_INDEX", "assistant-conversations")
FIELDS = ["id", "cluster_id", "question", "expected", "answer", "error", "latency_s", "asked_at"]
REQUIRED = {"id", "cluster_id", "question"}


def load_questions(path: str) -> list[dict]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: can mot danh sach cau hoi khong rong")
    seen: set[str] = set()
    for item in data:
        missing = REQUIRED - set(item)
        if missing:
            raise ValueError(f"cau hoi {item.get('id', '?')} thieu truong {sorted(missing)}")
        if item["id"] in seen:
            raise ValueError(f"id trung: {item['id']}")
        seen.add(item["id"])
    return data


def login(client: httpx.Client, username: str, password: str) -> str:
    response = client.post(f"{BASE_URL}/auth/login",
                           json={"username": username, "password": password},
                           headers={"X-CSRF-Protection": "1"})
    response.raise_for_status()
    return response.json()["token"]


def reset_conversation(client: httpx.Client, cluster_id: str) -> None:
    client.delete(f"{OPENSEARCH_URL}/{CONVERSATIONS_INDEX}/_doc/{cluster_id}")


def ask(client: httpx.Client, token: str, cluster_id: str, question: str) -> tuple[str, float]:
    started = time.monotonic()
    response = client.post(
        f"{BASE_URL}/assistant/clusters/{cluster_id}/conversation/messages",
        json={"message": question},
        headers={"Authorization": f"Bearer {token}"},
    )
    latency = round(time.monotonic() - started, 2)
    response.raise_for_status()
    answer = next((message.get("content") for message in reversed(response.json()["messages"])
                   if message.get("role") == "assistant" and message.get("content")), "")
    return answer, latency


def run(client: httpx.Client, questions: list[dict], *, token: str,
        reset: bool = True, delay: float = 0.0) -> list[dict]:
    rows = []
    for index, item in enumerate(questions):
        if reset:
            reset_conversation(client, item["cluster_id"])
        asked_at = datetime.now(timezone.utc).isoformat()
        try:
            answer, latency = ask(client, token, item["cluster_id"], item["question"])
            error = ""
        except Exception as exc:  # noqa: BLE001
            answer, latency, error = "", "", f"{type(exc).__name__}: {exc}"
        rows.append({"id": item["id"], "cluster_id": item["cluster_id"], "question": item["question"],
                     "expected": item.get("expected", ""), "answer": answer, "error": error,
                     "latency_s": latency, "asked_at": asked_at})
        print(f"[{index + 1}/{len(questions)}] {item['id']}: {error or f'{latency}s'}", flush=True)
        if delay and index < len(questions) - 1:
            time.sleep(delay)
    return rows


def write_csv(rows: list[dict], output: str) -> None:
    with open(output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Chay golden set qua AI Assistant that")
    parser.add_argument("--questions",
                        default=str(pathlib.Path(__file__).with_name("assistant-questions.json")))
    parser.add_argument("--output", required=True)
    parser.add_argument("--delay", type=float, default=10.0)
    parser.add_argument("--keep-history", action="store_true")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    with httpx.Client(timeout=300.0) as client:
        token = login(client, os.environ["QUERY_API_USERNAME"], os.environ["QUERY_API_PASSWORD"])
        started_at = datetime.now(timezone.utc).isoformat()
        rows = run(client, questions, token=token, reset=not args.keep_history, delay=args.delay)
        ended_at = datetime.now(timezone.utc).isoformat()

    write_csv(rows, args.output)
    failed = sum(1 for row in rows if row["error"])
    print(f"\n{len(rows)} cau hoi, {failed} loi -> {args.output}")
    print(f"Cua so de loc tren Langfuse: {started_at} .. {ended_at}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
