"""Capture GREEN results separately; never overwrite committed RED evidence."""

from datetime import datetime, timezone
import hashlib
from importlib import metadata, util
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
spec = util.spec_from_file_location("vt013_evidence_capture", HERE.parent / "red/run_red.py")
capture = util.module_from_spec(spec)
spec.loader.exec_module(capture)
capture.HERE = HERE


def describe(name):
    contracts = {
        "test_t02_": ("T-02 / AC-01", "Exact tool/Unicode history restored; creation time preserved", "schema validation; atomic snapshot; undo"),
        "test_t03_send": ("T-03 / AC-01", "Send exposes current revision and Undo availability", "version-aware write response; public projection"),
        "test_t03_undo": ("T-03 / AC-01", "First Send undone to persisted []; new revision; no AI call", "create-only Send; conditional Undo; consumed snapshot"),
        "test_t04_": ("T-04, T-05 / AC-01, AC-03", "Only latest turn restored; old token conflicts; no second Undo", "revision-first comparison; snapshot consumption"),
        "test_t06_": ("T-06 / AC-02", "Invalid/blank input returns 422 with no generation or write", "strict ChatRequest; length and whitespace validation"),
        "test_t07_": ("T-07 / AC-02", "Valid boundary text, including 4000 emoji, accepted unchanged", "raw-length validation; no API trimming"),
        "test_t08_": ("T-08 / AC-03", "Malformed request rejected with 422 before persistence", "strict UndoRequest; canonical revision parser"),
        "test_t09_": ("T-09 / AC-03", "Valid numeric boundary parsed; absent revision returns 409", "signed-64-bit bounds; missing-state conflict"),
        "test_t10_": ("T-10 / AC-03, AC-05", "Stale Undo returns 409 without touching newer history", "version comparison before any write"),
        "test_t11_": ("T-11 / AC-04", "Read failure returns 503; history preserved; no generation/write", "sanitized StorageError propagation"),
        "test_t12_missing_index_raises": ("T-12 / AC-04", "Actual repository raises StorageError for missing index", "typed NotFoundError classification"),
        "test_t12_": ("T-12 / AC-04", "Missing index returns 503, not empty success; no side effects", "no blanket 404 suppression"),
        "test_t13_": ("T-13 / AC-04", "Rejected Undo write returns 503 and retains prior snapshot", "write failure propagation; no success default"),
        "test_t14_": ("T-14 / AC-05", "Competing Sends yield one 200, one 409 and one commit", "CAS updates; create-only first creation"),
        "test_t15_": ("T-15, T-16 / AC-05", "Undo/Undo or Undo/Send has one winner; persisted state matches", "shared conditional-write path"),
        "test_t18_mapping_failures": ("T-18 / AC-04", "Mapping error or missing acknowledgement raises StorageError", "checked additive mapping update"),
        "test_t18_": ("T-18 / AC-01, AC-04", "Idempotent mapping upgrade preserves legacy data; no legacy Undo", "optional undo field; additive put_mapping"),
        "test_t19_": ("T-19 / authentication", "Undo returns 401 with Bearer challenge before storage", "existing router-level admin dependency retained"),
        "test_t22_": ("T-22 / AC-04", "Corrupt recovery data returns 503 without writing", "published schema validates stored snapshot"),
        "test_snapshot_": ("AC-01 / snapshot isolation", "Caller edits cannot change saved data or prior-history snapshot", "deep copies at read, snapshot and write boundaries"),
        "test_invalid_version_": ("AC-04 / metadata", "Missing or boolean version metadata returns 503; no write", "metadata validation without fabricated defaults"),
        "test_fake_": ("Infrastructure control", "Protocol fake fidelity assertions pass; not feature evidence", "no production behavior supplied by fake"),
    }
    for prefix, description in contracts.items():
        if name.startswith(prefix):
            return description
    regression = {
        "test_assistant_requires_admin": "401 and Bearer challenge for unauthenticated existing endpoints",
        "test_cum_khong_ton_tai": "Unknown cluster remains 404",
        "test_chua_hoi_lan_nao": "Absent conversation has [] messages, null revision and Undo false",
        "test_tra_ve_hoi_thoai": "Existing seeded conversation remains readable",
        "test_thieu_openai_key": "Unconfigured generation remains 503",
        "test_tra_loi_thang": "Direct answer persists; GET equals the complete POST response",
        "test_ai_goi_tool": "Tool round preserves user/assistant/tool/assistant order",
        "test_dat_gioi_han": "Configured tool-round limit still terminates generation",
        "test_hoi_tiep": "Follow-up generation receives old history and appends the new turn",
        "test_tool_khong_ton_tai": "Unknown tool returns an explicit error object",
        "test_get_cluster_history": "Unavailable tool store returns an explicit error object",
        "test_search_related_logs": "Default-window search returns the matching current log",
        "test_list_active_clusters": "Alerted record is retained and normal record excluded",
        "test_loi_trong_tool": "Tool exception becomes explicit error information",
        "test_ensure_ready_tao_index": "New mapping stays strict, including disabled snapshot indexing",
        "test_get_chua_co_conversation": "Genuine missing document returns None",
        "test_save_roi_get": "Versioned create/read returns identical persisted document",
        "test_save_lan_2": "Second conditional save preserves creation time and advances version",
        "test_ensure_ready_goi_lai": "Repeated readiness update is idempotent",
        "test_ensure_ready_bo_qua": "Creation race still ensures the required mapping",
    }
    for prefix, behavior in regression.items():
        if name.startswith(prefix):
            return "Assistant regression", behavior, "existing behavior retained; fixtures use the versioned repository contract"
    raise ValueError(f"Missing per-test description: {name}")


def write_case_report(report):
    lines = ["# GREEN results by test", "",
             "Generated from the final JUnit results. The 90 unique cases below exclude the combined rerun.", "",
             "| Evidence ID | Plan ID / AC | Test node ID | Result | Actual behavior verified | Relevant implementation |",
             "|---|---|---|---|---|---|"]
    count = 0
    for run in report["runs"]:
        path = Path(next(arg.split("=", 1)[1] for arg in run["command"] if arg.startswith("--junitxml=")))
        if path.name.startswith("combined-"):
            continue
        for case in ET.parse(path).iter("testcase"):
            count += 1
            parts = case.attrib["classname"].split(".")
            module = next(i for i, part in enumerate(parts) if part.startswith("test_"))
            node = f"tests/{parts[module]}.py::" + "::".join(parts[module + 1:] + [case.attrib["name"]])
            node = node.replace("\n", "\\n").replace("|", "\\|")
            plan, behavior, change = describe(case.attrib["name"])
            result = "PASS" if all(case.find(tag) is None for tag in ("failure", "error", "skipped")) else "NOT PASS"
            lines.append(f"| GREEN-{count:03} | {plan} | `{node}` | {result} | {behavior} | {change} |")
    (HERE / "test-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    groups = [
        ("focused-green", ["tests/test_assistant_undo_contract.py"]),
        ("assistant-regression", ["tests/test_assistant.py", "tests/test_assistant_storage.py"]),
        ("backend-contracts", ["tests/test_assistant_undo_backend.py"]),
        ("combined-backend", ["tests/test_assistant_undo_contract.py",
                              "tests/test_assistant_undo_backend.py",
                              "tests/test_assistant.py", "tests/test_assistant_storage.py"]),
    ]
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "interpreter": sys.executable, "python": sys.version,
        "packages": {name: metadata.version(name) for name in (
            "pytest", "fastapi", "starlette", "httpx", "pydantic", "opensearch-py", "jsonschema")},
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "query-api/src/assistant/storage.py", "query-api/src/assistant/router.py", "query-api/Dockerfile",
            "query-api/tests/test_assistant_undo_contract.py", "query-api/tests/vt013_opensearch_fake.py",
            "query-api/tests/test_assistant_undo_backend.py", "query-api/tests/test_assistant.py",
            "query-api/tests/test_assistant_storage.py", "docs/assignments/VT-013/plan.md",
            "docs/architect/contracts/assistant-conversation-schema.json", "docs/architect/contracts/api-contract.md")},
        "runs": [],
    }
    for name, files in groups:
        run = capture.run(name, files)
        report["runs"].append(run)
        counts = {}
        for case in run.get("cases", []):
            counts[case["status"]] = counts.get(case["status"], 0) + 1
        print(json.dumps({"run": name, "exit_code": run["exit_code"],
                          "timed_out": run["timed_out"], "counts": counts}), flush=True)
    (HERE / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8", newline="\n")
    if all(not run["timed_out"] for run in report["runs"]):
        write_case_report(report)
    return max(2 if run["timed_out"] else run["exit_code"] for run in report["runs"])


if __name__ == "__main__":
    raise SystemExit(main())
