"""Capture frontend checks without installing dependencies or touching old evidence."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
WEB = ROOT / "web"
PRODUCTION = ["web/src/lib/api.ts", "web/src/lib/queries.ts",
              "web/src/components/incident/AssistantPanel.tsx"]
TESTS = ["src/lib/assistant-undo.test.ts", "src/components/incident/AssistantPanel.test.tsx"]


def capture(name, command, timeout=180):
    print(f"Running {name}", flush=True)
    started = datetime.now(timezone.utc)
    env = os.environ.copy()
    # Existing API regression explicitly tests Jaeger being unconfigured.
    # Override only the test process, never read/modify the user's .env files.
    if "node_modules/vitest/vitest.mjs" in command:
        env["VITE_JAEGER_URL"] = ""
    try:
        result = subprocess.run(command, cwd=WEB, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout, env=env)
        output, code, timed_out = result.stdout, result.returncode, False
    except subprocess.TimeoutExpired as error:
        output, code, timed_out = error.stdout or b"", None, True
    info = {"command": command, "cwd": str(WEB), "exit_code": code,
            "timed_out": timed_out, "recorded_at_utc": started.isoformat(),
            "environment_overrides": {"VITE_JAEGER_URL": ""} if "node_modules/vitest/vitest.mjs" in command else {}}
    text = "\n".join(line.rstrip() for line in output.decode("utf-8", errors="replace").splitlines()) + "\n"
    (HERE / f"{name}.log").write_text(json.dumps(info, indent=2) + "\n\n" + text,
                                    encoding="utf-8", newline="\n")
    print(json.dumps({"run": name, "exit_code": code, "timed_out": timed_out}), flush=True)
    return info


def main():
    phase = sys.argv[1]
    assert phase in {"red", "green"}
    report = {
        "phase": phase, "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "production_sha256_before": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PRODUCTION},
        "test_sha256": {p: hashlib.sha256((WEB / p).read_bytes()).hexdigest() for p in TESTS},
        "versions": {p: json.loads((WEB / "node_modules" / p / "package.json").read_text(encoding="utf-8"))["version"]
                     for p in ("react", "@tanstack/react-query", "vitest", "@testing-library/react", "typescript", "vite")},
        "node": subprocess.check_output(["node", "--version"], text=True).strip(), "runs": [],
    }
    vitest = ["node", "node_modules/vitest/vitest.mjs", "run"]
    xml = HERE / f"{phase}-targeted.junit.xml"
    report["runs"].append(capture(f"{phase}-targeted", [*vitest, *TESTS, "--reporter=default", "--reporter=junit", f"--outputFile={xml}"]))
    if xml.exists():
        report["targeted_cases"] = [{"name": c.attrib["name"],
            "status": "failed" if c.find("failure") is not None else "error" if c.find("error") is not None
            else "skipped" if c.find("skipped") is not None else "passed"}
            for c in ET.parse(xml).iter("testcase")]
    if phase == "green":
        report["runs"].append(capture("green-regression", [*vitest, "--reporter=default", "--reporter=junit", f"--outputFile={HERE / 'green-regression.junit.xml'}"]))
        report["runs"].append(capture("typecheck", ["node", "node_modules/typescript/bin/tsc", "-b"]))
        report["runs"].append(capture("lint", ["node", "node_modules/oxlint/bin/oxlint"]))
        report["runs"].append(capture("build", ["node", "node_modules/vite/bin/vite.js", "build"]))
    report["production_sha256_after"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PRODUCTION}
    (HERE / f"{phase}-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return max(2 if r["timed_out"] else r["exit_code"] for r in report["runs"])


if __name__ == "__main__":
    raise SystemExit(main())
