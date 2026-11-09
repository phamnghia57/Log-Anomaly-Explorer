# VT-013 M-01 — swallowed read exception

## Conclusion: KILLED

One deliberate mutant was introduced in a detached disposable Git worktree.
Four existing assertions detected it; no test or expectation was edited.
The assignment branch's production source was never mutated. The temporary source
was restored byte-for-byte, tested again and its worktree removed without force.
No branch/commit was created, and nothing was pushed or merged.

Branch: `feat/vt013-undo-manhpd`; unchanged HEAD:
`a275c52300d40e92681692a0cc894a9946cb0084`.
Tracked worktree and index were clean before/after. Pre-existing untracked files
were preserved; only this new evidence directory was added.

The concise pipe-delimited record is in `report.txt`. Exact commands, per-case
results, source/evidence hashes and worktree cleanup records are in `results.json`.

## Oracle reviewed before mutation

`query-api/src/assistant/storage.py:113`, `ConversationRepository.get`, uses the real
repository over the test transport. A genuine document-not-found outcome means
absence and may return None. A missing index is not an empty conversation: its
typed NotFoundError handler raises StorageError. Other read/validation exceptions
are converted to `StorageError("cannot read conversation")` at line 128.

The error escapes the Assistant router to the existing StorageError handler in
`query-api/src/main.py:130`, returning HTTP 503 and `error=storage_unavailable`.
This implements AC-04: unavailable/corrupt storage must never become default success.

T-11 (`test_assistant_undo_contract.py:131`) seeds history, injects ConnectionError
and expects 503, the error envelope, no generation, no write and unchanged history.
Returning None instead falsely reports that no document exists and allows Send to
continue from empty history. These are contract/status and persistence oracles, not
assertions on the handler's implementation text.

T-12 covers the actual repository's missing-index exception and both API GET/POST
503 contracts. Its handler was deliberately left intact. Other existing tests reject
corrupt snapshots and missing/boolean version metadata; swallowing those errors
also violates AC-04.

## Exact single mutation

Target: only the generic read exception handler of `ConversationRepository.get`.
The unique `raise StorageError("cannot read conversation") from None` was replaced
by `return None`. No NotFoundError, write, mapping or other handler was changed.
Git numstat confirmed exactly **one line added, one deleted, one production file**.
See `mutation.diff` for the exact zero-context diff. No test file changed in the
temporary worktree. Both worktrees used the same committed tests and schema.

## Executed results

- `baseline.log` / `baseline.junit.xml`: **90 PASS**, exit **0**, assignment worktree.
- `mutant.log` / `mutant.junit.xml`: **86 PASS, 4 FAIL**, exit **1**, temporary worktree.
- `restored.log` / `restored.junit.xml`: **90 PASS**, exit **0**, restored temporary source.
- `assignment-final.log` / `assignment-final.junit.xml`: **90 PASS**, exit **0**, original
  assignment worktree after temporary worktree removal.

These are repeat executions of the same 90 cases, not 360 unique tests. Every run
collected/executed all 90; there were no import/collection/setup errors, timeouts or
skips. The expected mutant pytest exit 1 is not an environment blocker. The capture
runner exits 0 when this experiment is successfully killed/restored/cleaned up.

Detecting tests, all failing at `assert response.status_code == 503`:

- T-11: `test_t11_read_failure_returns_503_and_preserves_history` — observed **409**.
- T-22: `test_t22_corrupt_snapshot_is_not_an_empty_success` — observed **409**.
- Metadata: `test_invalid_version_metadata_is_not_defaulted[metadata0]` — observed **409**.
- Metadata: `test_invalid_version_metadata_is_not_defaulted[metadata1]` — observed **409**.

For T-11, the initial status assertion kills the mutant. Subsequent assertions about
generation/writes/history are not reached in that failed test, and are not claimed
as independently observed failures. The observed 409 is consistent with Send treating
the failed read as absence and reaching a create-only conflict against the existing
document. The remaining version/create protection therefore limits the consequence;
this experiment does not claim that existing history was actually overwritten or
that T-11 returned HTTP 200. The wrong error classification alone violates AC-04.

All three T-12 cases **PASS even with the mutant**: its direct repository assertion
and GET/POST assertions continue receiving StorageError/503 through the unchanged
typed missing-index handler. The six repository regression tests and mapping-error
assertions also pass. They are scope controls, not additional mutant kills.

## Restoration and evidence integrity

Assignment original, isolated original, isolated restored and assignment final
source SHA-256 are identical:

`ddaaf6057906c6d7242b1ebcdc79ff43101606d127c31f56575504ea1b2240e2`

Mutant source SHA-256:

`16b59aacdfbe6aff612c49bf751ad4e39e9e4bbe4d0d2df14463fd586425eec2`

`results.json` records the exact temporary absolute path, detached HEAD, clean status
after restoration, successful `git worktree remove`, path absence, and before/after
worktree inventory. No force removal, branch deletion or prune was used. The ordinary
assignment worktree and the separate dev worktree are retained.

Every pre-existing tracked/untracked file outside this new mutation directory was
hashed before and checked after execution: `changed_preexisting_files=[]`. This
includes approved plan, RED/GREEN/integration/frontend evidence, tests and frontend
code. Existing evidence hashes are preserved in the JSON. Final `git diff --check`
and `git diff --stat` returned 0 with no tracked changes; untracked new evidence does
not appear in that stat. No mutation remains in the assignment source.

## Reproduce

From the repository root, using the existing backend development environment:

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B docs/assignments/VT-013/evidence/mutation/run_mutation.py
```

The runner creates a new uniquely named detached worktree under `D:/SE`, performs
the single mutation, restores it in a finally block, checks ownership/head/cleanliness
and removes that exact worktree. Baseline/restored/final tests require exit 0 and all
90 passes. The mutant must produce executed assertion failures, including T-11; it
cannot be counted killed merely by an import error. All pytest command arrays and
working directories are saved in their log headers and `results.json`.

The last assignment-final check was appended with the same capture/test function
after the initial orchestration completed; the reproducible runner now performs that
same extra check automatically after removal. No test assertion changed for this step.

This machine's Windows sandbox can block TestClient loopback initialization; the
recorded run used approved execution outside that sandbox. No dependency was installed.
The existing transport fake and deterministic generation were reused. This mutation
phase does not rerun Docker, real OpenSearch or browser E2E, and makes no new claim
about them. No frontend change, performance test, commit, push or PR was performed.
Copy/archive the evidence before reproducing because log names are fixed.
