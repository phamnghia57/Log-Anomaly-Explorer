"""One isolated exception-swallowing mutant; never edit the assignment source."""

from datetime import datetime, timezone
import hashlib
from importlib import metadata, util
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SOURCE = "query-api/src/assistant/storage.py"
TESTS = ["tests/test_assistant_undo_contract.py", "tests/test_assistant_undo_backend.py",
         "tests/test_assistant.py", "tests/test_assistant_storage.py"]
spec = util.spec_from_file_location("vt013_mutation_capture", HERE.parent / "red/run_red.py")
capture = util.module_from_spec(spec)
spec.loader.exec_module(capture)
capture.HERE = HERE


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inventory():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    paths += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    return {p: sha((ROOT / p).read_bytes()) for p in paths
            if p and not p.startswith("docs/assignments/VT-013/evidence/mutation/") and (ROOT / p).is_file()}


def git(name, args, cwd=ROOT):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    info = {"command": ["git", *args], "cwd": str(cwd), "exit_code": result.returncode,
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace")}
    report["git_commands"].append(info)
    print(f"{name}: exit {result.returncode}", flush=True)
    if result.returncode:
        raise RuntimeError(f"{name} failed: {info['stderr']}")
    return info["stdout"]


def tests(name, root):
    capture.WORKDIR = root / "query-api"
    result = capture.run(name, TESTS, timeout=180)
    report["runs"].append(result)
    counts = {s: sum(c["status"] == s for c in result.get("cases", []))
              for s in ["passed", "failed", "error", "skipped"]}
    print(json.dumps({"run": name, "exit_code": result["exit_code"], "counts": counts}), flush=True)
    return result


report = {"mutation_id": "M-01", "started_at_utc": datetime.now(timezone.utc).isoformat(),
          "interpreter": sys.executable, "python": sys.version,
          "packages": {p: metadata.version(p) for p in ["pytest", "fastapi", "opensearch-py", "httpx"]},
          "git_commands": [], "runs": [], "conclusion": "NOT VERIFIED"}


def main():
    temp = (ROOT.parent / ("vt013-mutation-" + uuid4().hex[:12])).resolve()
    created = False
    original = None
    before = inventory()
    report["assignment_source_original_sha256"] = before[SOURCE]
    report["preexisting_file_count"] = len(before)
    report["evidence_original_hashes"] = {p: v for p, v in before.items()
        if p.startswith("docs/assignments/VT-013/evidence/")}
    try:
        report["branch"] = git("branch", ["branch", "--show-current"]).strip()
        report["head"] = git("head", ["rev-parse", "HEAD"]).strip()
        assert report["branch"] == "feat/vt013-undo-manhpd"
        assert report["head"] == "a275c52300d40e92681692a0cc894a9946cb0084"
        assert not git("tracked-status", ["status", "--porcelain=v1", "--untracked-files=no"])
        report["worktrees_before"] = git("worktrees-before", ["worktree", "list", "--porcelain"])
        baseline = tests("baseline", ROOT)
        assert baseline["exit_code"] == 0 and len(baseline["cases"]) == 90
        assert all(c["status"] == "passed" for c in baseline["cases"])
        assert temp.parent == ROOT.parent.resolve() and temp.name.startswith("vt013-mutation-") and not temp.exists()
        report["temporary_worktree"] = str(temp)
        git("create-detached-worktree", ["worktree", "add", "--detach", str(temp), report["head"]])
        created = True
        assert git("isolated-head", ["rev-parse", "HEAD"], temp).strip() == report["head"]
        original = (temp / SOURCE).read_bytes()
        report["isolated_source_original_sha256"] = sha(original)
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        needle = b'        except Exception:' + newline + b'            raise StorageError("cannot read conversation") from None'
        replacement = b'        except Exception:' + newline + b'            return None'
        assert original.count(needle) == 1
        (temp / SOURCE).write_bytes(original.replace(needle, replacement, 1))
        report["isolated_source_mutant_sha256"] = sha((temp / SOURCE).read_bytes())
        diff = git("mutation-diff", ["diff", "--unified=0", "--", SOURCE], temp)
        (HERE / "mutation.diff").write_text(diff, encoding="utf-8", newline="\n")
        assert git("mutation-numstat", ["diff", "--numstat"], temp).strip() == f"1\t1\t{SOURCE}"
        assert git("mutated-files", ["diff", "--name-only"], temp).strip() == SOURCE
        mutant = tests("mutant", temp)
        assert mutant["exit_code"] == 1 and len(mutant.get("cases", [])) == 90
        assert all(c["status"] in {"passed", "failed"} for c in mutant["cases"])
        killed = [c for c in mutant["cases"] if c["status"] == "failed"]
        assert any(c["name"] == "test_t11_read_failure_returns_503_and_preserves_history" for c in killed)
        report["detecting_assertions"] = killed
        # Restore exact original bytes, including this checkout's line endings.
        (temp / SOURCE).write_bytes(original)
        report["isolated_source_restored_sha256"] = sha((temp / SOURCE).read_bytes())
        assert report["isolated_source_restored_sha256"] == report["isolated_source_original_sha256"]
        assert not git("restored-isolated-diff", ["diff", "--name-only"], temp)
        restored = tests("restored", temp)
        assert restored["exit_code"] == 0 and len(restored["cases"]) == 90
        assert all(c["status"] == "passed" for c in restored["cases"])
        report["conclusion"] = "KILLED"
    except Exception as error:
        report["failure_or_blocker"] = f"{type(error).__name__}: {error}"
        print(report["failure_or_blocker"], flush=True)
    finally:
        if created:
            if original is not None:
                (temp / SOURCE).write_bytes(original)
            assert temp.resolve().parent == ROOT.parent.resolve() and temp.name.startswith("vt013-mutation-")
            assert git("cleanup-check-head", ["rev-parse", "HEAD"], temp).strip() == report["head"]
            assert not git("cleanup-check-status", ["status", "--porcelain=v1"], temp)
            git("remove-restored-worktree", ["worktree", "remove", str(temp)])
            report["temporary_worktree_removed"] = not temp.exists()
        report["worktrees_after"] = git("worktrees-after", ["worktree", "list", "--porcelain"])
        if report["conclusion"] == "KILLED":
            final = tests("assignment-final", ROOT)
            assert final["exit_code"] == 0 and len(final["cases"]) == 90
            assert all(c["status"] == "passed" for c in final["cases"])
        report["assignment_source_final_sha256"] = sha((ROOT / SOURCE).read_bytes())
        report["changed_preexisting_files"] = [p for p, digest in before.items()
            if not (ROOT / p).is_file() or sha((ROOT / p).read_bytes()) != digest]
        assert report["changed_preexisting_files"] == []
        assert report["assignment_source_final_sha256"] == report["assignment_source_original_sha256"]
        assert git("final-head", ["rev-parse", "HEAD"]).strip() == report["head"]
        assert not git("final-tracked-status", ["status", "--porcelain=v1", "--untracked-files=no"])
        git("diff-check", ["diff", "--check"])
        git("diff-stat", ["diff", "--stat"])
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (HERE / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if report["conclusion"] == "KILLED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
