"""VT-014 - "Who tests the tests?": mutation "doi mapping cua mot response field".

Moi mutant duoc ap vao BAN SAO TAM (tempdir) cua repo -> KHONG bao gio sua code that
trong nhanh nop bai. Chay pytest tren ban sao; test fail = mutant bi KILLED.

    python ingestion/tests/mutation/run_mutations.py            # tat ca mutant
    python ingestion/tests/mutation/run_mutations.py M1 M2      # chon mutant
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TESTS = ["tests/test_ingest_core.py", "tests/test_idempotency.py", "tests/test_idempotency_api.py"]

# (id, file, chuoi goc, chuoi mutant, mo ta)
MUTANTS = [
    ("M1", "ingestion/src/ingest_core.py",
     'return Result(202, {"accepted": True, "log_id": log_id})',
     'return Result(202, {"accepted": True, "log_id": payload["trace_id"]})',
     "response.log_id map nham sang payload.trace_id"),
    ("M2", "ingestion/src/ingest_core.py",
     '"log_ids": [log_id for log_id, _ in items]})',
     '"log_ids": [log_id for log_id, _ in reversed(items)]})',
     "response.log_ids map sai thu tu (log_ids[i] khong ung voi payload[i])"),
    ("M3", "ingestion/src/ingest_core.py",
     'return Result(previous.status, previous.body, {REPLAY_HEADER: "true"})',
     'return Result(202, previous.body, {REPLAY_HEADER: "true"})',
     "replay map status co dinh 202 thay vi status da luu"),
    ("M4", "ingestion/src/ingest_core.py",
     'return Result(409, {"accepted": False, "reason": "idempotency_key_reused",',
     'return Result(409, {"accepted": False, "reason": "schema_validation_failed",',
     "response.reason cua 409 map sang ma loi khac"),
    ("M5", "ingestion/src/ingest_core.py",
     'return Result(202, {"accepted": True, "accepted_count": len(items),',
     'return Result(202, {"accepted": True, "accepted_count": len(payload),',
     "accepted_count map tu len(payload) (mutant tuong duong ky vong)"),
]


def run(mutant_ids: list[str]) -> int:
    selected = [m for m in MUTANTS if not mutant_ids or m[0] in mutant_ids]
    survived = 0
    for mid, rel, original, mutated, desc in selected:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            for part in ("ingestion", "docs/architect/contracts"):
                shutil.copytree(REPO / part, root / part,
                                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            target = root / rel
            text = target.read_text(encoding="utf-8")
            if text.count(original) != 1:
                print(f"{mid}: KHONG ap duoc (chuoi goc xuat hien {text.count(original)} lan)")
                return 2
            target.write_text(text.replace(original, mutated), encoding="utf-8")
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                   *TESTS], cwd=root / "ingestion", capture_output=True, text=True)
            failed = [ln.split(" - ")[0].replace("FAILED ", "")
                      for ln in proc.stdout.splitlines() if ln.startswith("FAILED")]
            status = "KILLED" if proc.returncode != 0 else "SURVIVED"
            survived += status == "SURVIVED"
            last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
            print(f"{mid} [{status}] {desc}\n    {last}")
            for name in failed:
                print(f"    killed by: {name}")
    print(f"\nTong: {len(selected)} mutant, {len(selected) - survived} killed, {survived} survived")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
