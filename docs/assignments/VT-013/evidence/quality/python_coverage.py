"""stdlib trace, including worker threads; no claim of Python branch coverage."""
from pathlib import Path
import json
import os
import sys
import trace

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
TARGETS = [ROOT / "query-api/src/assistant/storage.py", ROOT / "query-api/src/assistant/router.py"]
os.chdir(ROOT / "query-api")
sys.path.insert(0, str(ROOT))
tracer = trace.Trace(count=True, trace=False, ignoredirs=[sys.prefix, sys.base_prefix])
namespace = {"pytest": pytest, "args": ["-v", "--tb=short", "-p", "no:cacheprovider",
    f"--junitxml={HERE / 'python-coverage.junit.xml'}", "tests/test_assistant_undo_contract.py",
    "tests/test_assistant_undo_backend.py", "tests/test_assistant.py", "tests/test_assistant_storage.py"]}
tracer.runctx("exit_code = pytest.main(args)", namespace, namespace)
results = tracer.results()
report = {}
for path in TARGETS:
    # CPython 3.14 may expose artificial None/zero position entries. They are
    # not source lines and must not enter the line-coverage denominator.
    statements = {n for n in trace._find_executable_linenos(str(path)) if isinstance(n, int) and n > 0}
    executed = {line for (file, line), count in results.counts.items()
                if Path(file).resolve() == path.resolve() and count}
    hit = statements & executed
    missing = sorted(statements - executed)
    report[path.relative_to(ROOT).as_posix()] = {"executable_lines": len(statements),
        "covered_lines": len(hit), "line_percent": round(100 * len(hit) / len(statements), 2),
        "missing_lines": missing, "executed_lines": sorted(executed),
        "branch_percent": None, "branch_note": "NOT MEASURED: stdlib trace has no branch instrumentation"}
    lines = path.read_text(encoding="utf-8").splitlines()
    (HERE / (path.stem + ".cover.txt")).write_text("\n".join(
        f"{i:4} {'HIT' if i in executed else 'MISS' if i in statements else '    '}: {line}"
        for i, line in enumerate(lines, 1)) + "\n", encoding="utf-8")
(HERE / "python-coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
raise SystemExit(namespace["exit_code"])
