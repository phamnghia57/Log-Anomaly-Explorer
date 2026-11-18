"""Offline contract tests; mock responses are never evidence of a deployed golden run."""
import copy
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

GOLDEN = Path(__file__).parent / "golden"
EVIDENCE = Path(__file__).resolve().parents[2] / "docs/evidence/11-assistant-golden-set"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_module("prepare_runner_test", GOLDEN / "run_assistant_golden.py")
with patch.dict(sys.modules, {"run_assistant_golden": runner}):
    prep = load_module("golden_prepare_test", GOLDEN / "prepare_assistant_golden.py")


@pytest.fixture
def catalog():
    return runner.load_questions(str(GOLDEN / "assistant-questions.json"), allow_unbound=True)


@pytest.fixture
def bindings():
    return {ref: f"cluster-{ref}" for ref in prep.FAULTS}


def cluster(ref, cluster_id):
    error_type, message = prep.FAULTS[ref]
    log_id = f"log-{ref}"
    return {"cluster_id": cluster_id, "signature": message, "score": 4.0,
            "status": "anomalous", "first_seen": "2026-01-01T00:00:00Z",
            "last_seen": "2026-01-01T00:01:00Z", "log_ids": [log_id], "logs_total": 1,
            "logs": [{"log_id": log_id, "timestamp": "2026-01-01T00:00:00Z",
                      "service": "demo-web", "level": "ERROR", "message": message,
                      "trace_id": "1" * 32, "span_id": "2" * 16,
                      "metadata": {"error_type": error_type}}],
            "incident": {"note": "unrelated operator note"}}


def test_catalog_is_complete_and_mirrored(catalog):
    prep.validate_catalog(catalog)
    assert len({q["id"] for q in catalog}) == 20
    assert Counter(q["category"] for q in catalog) == dict.fromkeys(prep.CATEGORIES, 4)
    assert all(q["cluster_id"] is None and q["expected"].strip() for q in catalog)
    assert json.loads((EVIDENCE / "questions.json").read_text(encoding="utf-8")) == catalog
    with pytest.raises(ValueError, match="cluster_id"):
        runner.load_questions(str(GOLDEN / "assistant-questions.json"))


def test_templates_have_all_questions_and_no_fake_ratings(catalog):
    ids = [q["id"] for q in catalog]
    for tool_rounds in (1, 2):
        for rater in ("a", "b"):
            path = EVIDENCE / f"rater-{rater}-round{tool_rounds}.template.csv"
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            assert [r["id"] for r in rows] == ids
            assert all(set(r) == {"id", "tool_rounds", "rater_id", "answer_ref", "layer_status",
                                  "evidence", "no_fabrication", "rationale", "evidence_ref"}
                       for r in rows)
            for row in rows:
                assert row["tool_rounds"] == str(tool_rounds)
                assert all(row[field] == "" for field in row if field not in {"id", "tool_rounds"})
    with (EVIDENCE / "adjudication.template.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 40
    assert {(r["tool_rounds"], r["id"]) for r in rows} == {
        (str(n), q) for n in (1, 2) for q in ids}
    assert all(None not in r and all(r[k] == "" for k in r if k not in {"id", "tool_rounds"})
               for r in rows)
    with (EVIDENCE / "summary.template.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert all(None not in r and all(r[k] == "" for k in r if k not in {"tool_rounds", "question_count"})
               for r in rows)


@pytest.mark.parametrize("change", ["size", "category", "ref", "expected", "bound", "duplicate"])
def test_invalid_catalog_rejected(catalog, change):
    if change == "size":
        catalog.pop()
    elif change == "category":
        catalog[0]["category"] = {}
    elif change == "ref":
        catalog[-1]["cluster_ref"] = "bad_schema"
    elif change == "expected":
        catalog[0]["expected"] = ""
    elif change == "bound":
        catalog[0]["cluster_id"] = "cluster-from-another-run"
    else:
        catalog[0]["id"] = catalog[1]["id"]
    with pytest.raises(ValueError):
        prep.validate_catalog(catalog)


@pytest.mark.parametrize("change", ["missing", "extra", "empty", "placeholder", "duplicate", "list"])
def test_invalid_bindings_rejected(bindings, change):
    if change == "missing":
        bindings.pop("value-422")
    elif change == "extra":
        bindings["bad_schema"] = "not-a-cluster"
    elif change == "empty":
        bindings["value-422"] = None
    elif change == "placeholder":
        bindings["value-422"] = "DOI-THANH-CLUSTER-ID-THAT"
    elif change == "duplicate":
        bindings["value-422"] = bindings["runtime-500"]
    else:
        bindings = []
    with pytest.raises(ValueError):
        prep.validate_bindings(bindings)


def test_prepare_verifies_context_and_writes_hashes_without_mutating_input(tmp_path, catalog, bindings):
    original = copy.deepcopy(catalog)
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer secret-test-token"
        assert request.url.params["logs_limit"] == "5"
        cluster_id = request.url.path.rsplit("/", 1)[-1]
        ref = next(ref for ref, cid in bindings.items() if cid == cluster_id)
        return httpx.Response(200, json=cluster(ref, cluster_id))

    output = tmp_path / "prepared"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        manifest = prep.prepare_dataset(client, catalog, bindings, token="secret-test-token",
                                        output=output, base_url="https://example.test/api/")
    assert len(seen) == 4 and all(r.url.path.startswith("/api/clusters/") for r in seen)
    assert catalog == original
    bound = runner.load_questions(str(output / "questions.json"))
    assert len(bound) == 20
    assert all(q["cluster_id"] == bindings[q["cluster_ref"]] for q in bound)
    assert all(q["cluster_id"] == bindings["runtime-500"] for q in bound if q["category"] == "bad_schema")
    assert manifest["status"] == "prepared_not_measured"
    assert manifest["verified_at"].endswith("+00:00")
    assert len(manifest["files"]) == 5
    for path, digest in manifest["files"].items():
        data = (output / path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert b"\r\n" not in data
        assert b"secret-test-token" not in data and b"operator note" not in data
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == manifest


@pytest.mark.parametrize("change", ["id", "no_logs", "no_log_ids", "wrong_fault", "mixed_fault",
                                    "outside_context", "mixed_service", "too_many", "missing_metadata"])
def test_unusable_cluster_rejected_before_output(tmp_path, catalog, bindings, change):
    payload = cluster("value-422", bindings["value-422"])
    if change == "id":
        payload["cluster_id"] = "another-cluster"
    elif change == "no_logs":
        payload["logs"] = []
    elif change == "no_log_ids":
        payload["log_ids"] = []
    elif change == "wrong_fault":
        payload["logs"][0]["metadata"]["error_type"] = "runtime"
    elif change in {"mixed_fault", "mixed_service"}:
        other = copy.deepcopy(payload["logs"][0])
        other["log_id"] = "another-log"
        other["message" if change == "mixed_fault" else "service"] = "different"
        payload["logs"].append(other)
        payload["log_ids"].append(other["log_id"])
    elif change == "outside_context":
        payload["log_ids"] = ["1", "2", "3", "4", "5", payload["logs"][0]["log_id"]]
    elif change == "too_many":
        payload["logs"] *= 6
    else:
        payload["logs"][0].pop("metadata")
    output = tmp_path / "prepared"
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ValueError):
            prep.prepare_dataset(client, catalog, bindings, token="t", output=output)
    assert not output.exists()


@pytest.mark.parametrize("status", [401, 404, 500])
def test_http_failure_does_not_create_output(tmp_path, catalog, bindings, status):
    output = tmp_path / "prepared"
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            prep.prepare_dataset(client, catalog, bindings, token="t", output=output)
    assert not output.exists()


def test_existing_output_is_preserved_without_http(tmp_path, catalog, bindings):
    output = tmp_path / "prepared"
    output.mkdir()
    (output / "manifest.json").write_text("existing evidence", encoding="utf-8")
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("must not call HTTP"))) as client:
        with pytest.raises(FileExistsError):
            prep.prepare_dataset(client, catalog, bindings, token="t", output=output)
    assert (output / "manifest.json").read_text(encoding="utf-8") == "existing evidence"


def test_failure_on_last_binding_keeps_output_absent(tmp_path, catalog, bindings):
    seen = []

    def handler(request):
        cid = request.url.path.rsplit("/", 1)[-1]
        ref = next(ref for ref, value in bindings.items() if value == cid)
        seen.append(ref)
        if ref == "runtime-500":
            return httpx.Response(404)
        return httpx.Response(200, json=cluster(ref, cid))

    output = tmp_path / "prepared"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            prep.prepare_dataset(client, catalog, bindings, token="t", output=output)
    assert len(seen) == 4 and not output.exists()


@pytest.mark.parametrize("url", ["file:///data", "ftp://example.test", "https://user:secret@example.test",
                                  "https://example.test?token=secret", "https://example.test#secret"])
def test_base_url_rejects_credentials_and_non_http(url):
    with pytest.raises(ValueError):
        prep.safe_base_url(url)


def test_prepare_cli_uses_login_and_never_calls_model(tmp_path, monkeypatch, bindings):
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(bindings), encoding="utf-8")
    monkeypatch.setenv("QUERY_API_USERNAME", "test-admin")
    monkeypatch.setenv("QUERY_API_PASSWORD", "test-password")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/auth/login"):
            assert request.method == "POST" and request.headers["X-CSRF-Protection"] == "1"
            assert json.loads(request.content) == {"username": "test-admin", "password": "test-password"}
            return httpx.Response(200, json={"token": "test-token"})
        assert request.method == "GET"
        cid = request.url.path.rsplit("/", 1)[-1]
        ref = next(ref for ref, value in bindings.items() if value == cid)
        return httpx.Response(200, json=cluster(ref, cid))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(prep.httpx, "Client", lambda **kw: client)
    output = tmp_path / "prepared"
    assert prep.main(["--bindings", str(path), "--output", str(output)]) == 0
    assert len(calls) == 5
    for file in output.rglob("*.json"):
        assert "test-password" not in file.read_text(encoding="utf-8")


def test_unfilled_binding_example_fails_cli_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(prep.httpx, "Client", lambda **kw: pytest.fail("must not connect"))
    output = tmp_path / "prepared"
    with pytest.raises(SystemExit) as exc:
        prep.main(["--bindings", str(GOLDEN / "cluster-bindings.example.json"), "--output", str(output)])
    assert exc.value.code == 2 and not output.exists()
