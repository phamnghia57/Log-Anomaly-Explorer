"""Verification-only runner; every historical evidence path remains untouched."""
from datetime import datetime, timezone
import hashlib
from importlib import util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
TESTS = ["tests/test_assistant_undo_contract.py", "tests/test_assistant_undo_backend.py",
         "tests/test_assistant.py", "tests/test_assistant_storage.py"]


def module(name, path):
    spec = util.spec_from_file_location(name, path)
    value = util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(name, argv, cwd, env, timeout=240):
    print("Running " + name, flush=True)
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        code, output = p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        code, output = None, e.stdout or b""
    r = {"name": name, "command": argv, "cwd": str(cwd), "exit_code": code}
    (HERE / (name + ".log")).write_text(json.dumps(r, indent=2) + "\n\n" +
        "\n".join(x.rstrip() for x in output.decode("utf-8", errors="replace").splitlines()) + "\n", encoding="utf-8")
    report["runs"].append(r)
    print(json.dumps(r), flush=True)
    return code


def inventory():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    paths += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths if p and
            not p.startswith("docs/assignments/VT-013/evidence/quality/") and (ROOT / p).is_file()}


report = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "runs": [], "e2e": []}


def main():
    before = inventory()
    report["branch"] = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    report["head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert report["branch"] == "feat/vt013-undo-manhpd" and report["head"].startswith("bc73525")
    assert not subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT)
    env = os.environ.copy()
    env.update(STORAGE_BACKEND="memory", OTEL_EXPORTER_OTLP_ENDPOINT="", LANGFUSE_TRACING_ENABLED="false",
               PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               VITE_JAEGER_URL="", PYTHONPATH=str(HERE))
    for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "PYTEST_ADDOPTS"]:
        env.pop(key, None)
    try:
        run("python-coverage", [sys.executable, "-u", "-B", str(HERE / "python_coverage.py")], ROOT, env)
        base = [sys.executable, "-u", "-B", "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider"]
        for name, files in [("backend-reverse", list(reversed(TESTS))),
                            ("backend-focused", [TESTS[0]]), ("repository-alone", [TESTS[3]])]:
            run(name, base + [f"--junitxml={HERE / (name + '.junit.xml')}", *files], ROOT / "query-api", env)
        run("races-100", base + ["-p", "repeat_plugin", f"--junitxml={HERE / 'races-100.junit.xml'}",
            TESTS[0] + "::test_t14_concurrent_sends_cannot_silently_overwrite",
            TESTS[1] + "::test_t15_t16_competing_undo_mutations_use_the_same_version"], ROOT / "query-api", env)
        vitest = ["node", "node_modules/vitest/vitest.mjs", "run"]
        for seed in [13013, 13014]:
            run(f"frontend-order-{seed}", vitest + ["--sequence.shuffle", f"--sequence.seed={seed}",
                "--reporter=default", "--reporter=junit", f"--outputFile={HERE / ('frontend-order-' + str(seed) + '.junit.xml')}"], ROOT / "web", env)
        tools = ROOT.parent / "vt013-quality-tools/node_modules/vitest/vitest.mjs"
        if tools.exists():
            run("frontend-coverage", ["node", "node_modules/vitest/vitest.mjs", "run", "--config", str(ROOT / "web/vitest.config.ts"),
                "--coverage.enabled", "--coverage.provider=v8", "--coverage.reporter=json", "--coverage.reporter=text",
                "--coverage.reporter=lcov", f"--coverage.reportsDirectory={HERE / 'frontend-coverage'}",
                "--coverage.include=src/lib/api.ts", "--coverage.include=src/lib/queries.ts",
                "--coverage.include=src/components/incident/AssistantPanel.tsx"], ROOT / "web", env)
        else:
            report["frontend_coverage_limitation"] = "Temporary provider unavailable; NOT MEASURED"
        for iteration in range(1, 11):
            folder = HERE / f"e2e-{iteration:02}"
            folder.mkdir(exist_ok=False)
            m = module(f"vt013_quality_e2e_{iteration}", HERE.parent / "frontend/run_e2e.py")
            m.HERE = folder
            original = m.command
            def redirected(name, argv, timeout=60, env=None):
                if "--config=playwright.vt013.config.ts" in argv:
                    argv = [str(x).replace("--config=playwright.vt013.config.ts", "--config=" + str(HERE / "playwright.quality.config.ts")) for x in argv]
                    env = dict(env, QUALITY_E2E_ARTIFACTS=str(folder))
                return original(name, argv, timeout=timeout, env=env)
            m.command = redirected
            code = m.main()
            report["e2e"].append({"iteration": iteration, "exit_code": code, "result": m.report["result"],
                                  "owned_container_removed": m.report.get("owned_container_removed", False)})
            print(json.dumps(report["e2e"][-1]), flush=True)
    finally:
        report["changed_preexisting_files"] = [p for p,v in before.items() if not (ROOT/p).is_file() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=v]
        report["preexisting_files_verified"] = len(before)
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (HERE / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(x["exit_code"] == 0 for x in report["runs"] + report["e2e"]) and not report["changed_preexisting_files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
