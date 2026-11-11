"""Line + branch coverage KHONG can coverage.py (dung sys.monitoring, Python >= 3.12).

Dung khi moi truong khong cai duoc pytest-cov. Neu co pytest-cov, uu tien:
    pytest --cov=src --cov-branch --cov-report=term-missing tests/test_idempotency.py

    cd ingestion
    python tests/tools/coverage_stdlib.py src/idempotency.py src/ingest_core.py -- \
        tests/test_ingest_core.py tests/test_idempotency.py

Branch = moi lenh nhay co dieu kien (POP_JUMP_IF_*, FOR_ITER) co 2 huong; dem so huong
da di qua / tong so huong. Bo qua nhanh exception-exit cua `with` (khong phai quyet dinh
cua lap trinh vien).
"""

from __future__ import annotations

import dis
import sys
from pathlib import Path

COND_JUMPS = {"POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "POP_JUMP_IF_NONE",
              "POP_JUMP_IF_NOT_NONE", "FOR_ITER"}


def walk_code(code):
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            yield from walk_code(const)


def static_info(path: Path):
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    lines, branches = set(), {}
    for co in walk_code(code):
        lines.update(ln for _, _, ln in co.co_lines() if ln is not None)
        instructions = list(dis.get_instructions(co))
        for i, ins in enumerate(instructions):
            # Bo qua nhanh "an" do CPython sinh cho loi thoat khoi `with` (WITH_EXCEPT_START)
            context = {x.opname for x in instructions[max(0, i - 3):i]}
            if ins.opname in COND_JUMPS and "WITH_EXCEPT_START" not in context:
                branches[(co.co_firstlineno, co.co_name, ins.offset)] = ins.positions.lineno
    lines.discard(0)
    return lines, branches


def main() -> int:
    argv = sys.argv[1:]
    sep = argv.index("--")
    targets = [Path(p).resolve() for p in argv[:sep]]
    pytest_args = argv[sep + 1:]
    names = {str(t) for t in targets}
    hit_lines: dict[str, set[int]] = {n: set() for n in names}
    hit_branches: dict[str, set] = {n: set() for n in names}

    mon = sys.monitoring
    tool = mon.COVERAGE_ID
    mon.use_tool_id(tool, "vt014-cov")

    def on_line(code, line):
        if code.co_filename in names:
            hit_lines[code.co_filename].add(line)
        return None

    def on_branch(code, src, dst):
        if code.co_filename in names:
            hit_branches[code.co_filename].add((code.co_firstlineno, code.co_name, src, dst))
        return None

    mon.register_callback(tool, mon.events.LINE, on_line)
    mon.register_callback(tool, mon.events.BRANCH, on_branch)
    mon.set_events(tool, mon.events.LINE | mon.events.BRANCH)
    import pytest
    rc = pytest.main(["-q", "-p", "no:cacheprovider", *pytest_args])
    mon.set_events(tool, 0)
    mon.free_tool_id(tool)

    print("\n%-28s %10s %10s  %s" % ("file", "line %", "branch %", "missing lines / partial branches"))
    for target in targets:
        lines, branches = static_info(target)
        hit = hit_lines[str(target)] & lines
        taken: dict[tuple, set] = {}
        for first, name, src, dst in hit_branches[str(target)]:
            taken.setdefault((first, name, src), set()).add(dst)
        done = sum(min(2, len(taken.get(k, ()))) for k in branches)
        partial = sorted({ln for k, ln in branches.items() if len(taken.get(k, ())) < 2})
        missing = sorted(lines - hit)
        print("%-28s %9.1f%% %9.1f%%  missing=%s partial@%s" % (
            target.name, 100 * len(hit) / len(lines), 100 * done / (2 * len(branches) or 1),
            missing, partial))
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
