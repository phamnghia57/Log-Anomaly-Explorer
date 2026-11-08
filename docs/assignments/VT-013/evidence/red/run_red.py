"""Reproduce VT-013 RED evidence without installing or changing dependencies.

Run with an existing interpreter containing query-api/requirements-dev.txt.
--sandbox-probe records the separately classified Windows event-loop blocker.
"""

from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
WORKDIR = ROOT / "query-api"
TARGET = "tests/test_assistant_undo_contract.py"


def run(name, files, *, timeout=120, junit=True):
    command = [sys.executable, "-u", "-B", "-m", "pytest", "-vv", "--tb=short",
               "-rA", "--color=no", "-p", "no:cacheprovider",
               "-o", "faulthandler_timeout=20"]
    xml_path = HERE / f"{name}.junit.xml"
    if junit:
        command.append(f"--junitxml={xml_path}")
    command.extend(files)
    env = os.environ.copy()
    env.update(STORAGE_BACKEND="memory", OTEL_EXPORTER_OTLP_ENDPOINT="",
               LANGFUSE_TRACING_ENABLED="false", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "PYTEST_ADDOPTS"):
        env.pop(key, None)
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=WORKDIR, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
        output, exit_code, timed_out = result.stdout, result.returncode, False
    except subprocess.TimeoutExpired as error:
        output, exit_code, timed_out = error.stdout or b"", None, True
    info = {"command": command, "cwd": str(WORKDIR), "exit_code": exit_code,
            "timed_out": timed_out, "timeout_seconds": timeout,
            "duration_seconds": round(time.monotonic() - started, 3)}
    # Normalize terminal line endings/display whitespace for portable diffs.
    # Assertion content inside strings is preserved; JUnit remains available.
    text = "\n".join(line.rstrip() for line in output.decode(
        "utf-8", errors="replace").splitlines()) + "\n"
    (HERE / f"{name}.log").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n\n" + text,
        encoding="utf-8", newline="\n")
    if junit and not timed_out and xml_path.exists():
        info["cases"] = []
        for case in ET.parse(xml_path).iter("testcase"):
            failure, error, skipped = case.find("failure"), case.find("error"), case.find("skipped")
            status = ("failed" if failure is not None else "error" if error is not None
                      else "skipped" if skipped is not None else "passed")
            detail = failure if failure is not None else error
            info["cases"].append({"name": case.attrib["name"], "status": status,
                                  "message": detail.attrib.get("message", "")
                                  if detail is not None else ""})
        # Strip presentation-only line-end whitespace, not XML attribute data.
        rendered = "\n".join(line.rstrip() for line in xml_path.read_text(
            encoding="utf-8").splitlines()) + "\n"
        xml_path.write_text(rendered, encoding="utf-8", newline="\n")
    return info


def main():
    packages = {}
    for package in ("pytest", "fastapi", "starlette", "httpx", "anyio", "pydantic",
                    "opensearch-py", "PyJWT", "argon2-cffi", "langfuse",
                    "prometheus-fastapi-instrumentator", "opentelemetry-instrumentation-fastapi"):
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = None
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "interpreter": sys.executable, "python": sys.version,
        "platform": sys.platform, "implementation": platform.python_implementation(),
        "packages": packages,
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT,
                                           text=True).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         text=True).strip(),
        "environment_overrides": {"STORAGE_BACKEND": "memory",
                                  "OTEL_EXPORTER_OTLP_ENDPOINT": "",
                                  "LANGFUSE_TRACING_ENABLED": "false",
                                  "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                   for name in ("query-api/src/assistant/router.py",
                                "query-api/src/assistant/storage.py",
                                "docs/assignments/VT-013/plan.md",
                                "query-api/tests/test_assistant_undo_contract.py",
                                "query-api/tests/vt013_opensearch_fake.py")},
    }
    if "--sandbox-probe" in sys.argv:
        report["classification"] = "environment probe; not valid RED assertion evidence"
        report["runs"] = [run("sandbox-probe", [f"{TARGET}::test_t03_send_response_exposes_revision_contract"],
                              timeout=40, junit=False)]
        destination = HERE / "sandbox-probe.json"
    else:
        report["runs"] = [
            run("existing-tests", ["tests/test_assistant.py", "tests/test_assistant_storage.py"]),
            run("focused-red", [TARGET]),
            # Run legacy cases after the new fixtures to verify state restoration.
            run("combined-regression", [TARGET, "tests/test_assistant.py",
                                        "tests/test_assistant_storage.py"]),
        ]
        destination = HERE / "results.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    for result in report["runs"]:
        counts = {}
        for case in result.get("cases", []):
            counts[case["status"]] = counts.get(case["status"], 0) + 1
        print(json.dumps({key: result[key] for key in ("command", "exit_code", "timed_out")}
                         | {"counts": counts}, ensure_ascii=False), flush=True)
    last = report["runs"][-1]
    return 2 if last["timed_out"] else last["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
