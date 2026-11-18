"""Bind the reviewed question catalog to verified deployed clusters; no model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from run_assistant_golden import BASE_URL, load_questions, login, validate_questions

FAULTS = {
    "value-422": ("value", "Simulated validation failure: required item data is invalid"),
    "connection-502": ("connection", "Simulated connection failure: downstream dependency unreachable"),
    "timeout-504": ("runtime", "Simulated downstream timeout"),
    "runtime-500": ("runtime", "Simulated runtime failure"),
}
CATEGORIES = {*FAULTS, "bad_schema"}


def validate_catalog(questions: list[dict]) -> None:
    validate_questions(questions, allow_unbound=True)
    counts = dict.fromkeys(CATEGORIES, 0)
    for item in questions:
        category = item.get("category")
        if not isinstance(category, str) or category not in counts:
            raise ValueError(f"{item['id']}: category khong hop le")
        counts[category] += 1
        expected_ref = "runtime-500" if category == "bad_schema" else category
        if item.get("cluster_ref") != expected_ref or item["cluster_id"] is not None:
            raise ValueError(f"{item['id']}: catalog can cluster_ref dung nhom va cluster_id=null")
        if not isinstance(item.get("expected"), str) or not item["expected"].strip():
            raise ValueError(f"{item['id']}: thieu expected")
    if len(questions) != 20 or any(count != 4 for count in counts.values()):
        raise ValueError("catalog can 20 cau, 4 cau moi nhom")


def validate_bindings(bindings: object) -> dict[str, str]:
    if not isinstance(bindings, dict) or set(bindings) != set(FAULTS):
        raise ValueError(f"bindings can dung 4 khoa: {', '.join(FAULTS)}")
    validate_questions([{"id": ref, "question": ref, "cluster_id": cluster_id}
                        for ref, cluster_id in bindings.items()])
    if len(set(bindings.values())) != len(FAULTS):
        raise ValueError("bindings can 4 cluster ID khac nhau")
    return bindings


def safe_base_url(base_url: str) -> str:
    url = httpx.URL(base_url)
    if (url.scheme not in {"http", "https"} or not url.host or url.userinfo
            or url.query or url.fragment):
        raise ValueError("QUERY_API_HOST can HTTP(S) URL, khong credentials/query/fragment")
    return str(url).rstrip("/")


def verify_cluster(payload: object, ref: str, cluster_id: str) -> dict:
    if not isinstance(payload, dict) or payload.get("cluster_id") != cluster_id:
        raise ValueError(f"{ref}: cluster_id trong response khong khop")
    logs, log_ids = payload.get("logs"), payload.get("log_ids")
    if (not isinstance(logs, list) or not 1 <= len(logs) <= 5
            or not isinstance(log_ids, list) or not log_ids):
        raise ValueError(f"{ref}: can 1-5 log mau that thuoc cluster")
    error_type, message = FAULTS[ref]
    services = set()
    for log in logs:
        if (not isinstance(log, dict) or not isinstance(log.get("metadata"), dict)
                or not isinstance(log.get("log_id"), str) or not log["log_id"]
                or log["log_id"] not in log_ids[:5]
                or log.get("metadata", {}).get("error_type") != error_type
                or log.get("message") != message or log.get("level") != "ERROR"
                or not isinstance(log.get("service"), str) or not log["service"].strip()):
            raise ValueError(f"{ref}: log mau sai fault, tron nhom hoac khong thuoc 5 log dau")
        services.add(log["service"])
    if len(services) != 1:
        raise ValueError(f"{ref}: log mau tron service")
    # Retain the incident's actual cluster/log data, excluding unrelated operator notes.
    fields = ("cluster_id", "signature", "score", "status", "first_seen", "last_seen",
              "log_ids", "logs", "logs_total")
    return {field: payload[field] for field in fields if field in payload}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def prepare_dataset(client: httpx.Client, questions: list[dict], bindings: dict, *,
                    token: str, output: Path, base_url: str = BASE_URL) -> dict:
    validate_catalog(questions)
    validate_bindings(bindings)
    base_url = safe_base_url(base_url)
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"output da ton tai: {output}")
    snapshots = {}
    for ref in FAULTS:
        cluster_id = bindings[ref]
        response = client.get(f"{base_url}/clusters/{quote(cluster_id, safe='')}",
                              params={"logs_limit": 5},
                              headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        snapshots[ref] = verify_cluster(response.json(), ref, cluster_id)
    bound = [{**item, "cluster_id": bindings[item["cluster_ref"]]} for item in questions]
    validate_questions(bound)
    files = {"questions.json": _json_bytes(bound)}
    files.update({f"clusters/{ref}.json": _json_bytes(snapshot)
                  for ref, snapshot in snapshots.items()})
    manifest = {
        "status": "prepared_not_measured", "verified_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url, "bindings": bindings,
        "question_count": len(bound), "sample_logs_limit": 5,
        "catalog_sha256": hashlib.sha256(_json_bytes(questions)).hexdigest(),
        "catalog_hash_format": "UTF-8, ensure_ascii=False, indent=2, trailing LF",
        "bad_schema": "runtime-500 anchor; no quarantine evidence was collected",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    # Only create an output directory after all four bindings pass verification.
    output.mkdir(parents=True, exist_ok=False)
    (output / "clusters").mkdir()
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / "manifest.json").write_bytes(_json_bytes(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Xac minh 4 cluster that va gan 20 cau golden")
    parser.add_argument("--questions", default=str(Path(__file__).with_name("assistant-questions.json")))
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        questions = load_questions(args.questions, allow_unbound=True)
        validate_catalog(questions)
        bindings = validate_bindings(json.loads(Path(args.bindings).read_text(encoding="utf-8")))
        base_url = safe_base_url(BASE_URL)
        if Path(args.output).exists():
            raise FileExistsError(f"output da ton tai: {args.output}")
        with httpx.Client(timeout=30.0) as client:
            token = login(client, os.environ["QUERY_API_USERNAME"], os.environ["QUERY_API_PASSWORD"])
            prepare_dataset(client, questions, bindings, token=token, output=Path(args.output),
                            base_url=base_url)
    except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
        parser.error(str(exc))
    print(f"Da xac minh 4 cluster, xuat 20 cau -> {args.output}; chua goi model/cham diem")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
