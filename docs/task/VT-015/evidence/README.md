# VT-015 test-first execution evidence

Baseline HEAD: `50a3af1a159253d9f4d414fb54a4a90b1c4eba4a`.
Branch: `bt3/23001907-vt015` (already checked out at inspection; not recreated).
Executed on 2026-11-03 from `D:\Log-Anomaly-Explorer`, PowerShell.

## Commands and outcomes

Initial `python -m pytest -q query-api/tests` could not start because pytest was
not installed in the default interpreter. See baseline-environment-failure.txt.
This is environment evidence, not a baseline test failure or feature RED.

Created isolated local tooling with `python -m venv .venv-vt015`.
Installed dependencies with:

```powershell
./.venv-vt015/Scripts/python.exe -m pip install -r query-api/requirements-dev.txt
```

Initial sandbox network attempt failed; approved retry succeeded (exit 0).
Both installation logs are retained. The generated virtual environment is
ignored by Git via its generated ignore file; it is local tooling, not a deliverable.
python-version.txt and python-packages.txt record the resolved environment.

Baseline (new tests explicitly excluded, production and existing tests untouched):

```powershell
./.venv-vt015/Scripts/python.exe -m pytest -q query-api/tests --ignore=query-api/tests/test_vt015_approval.py
```

Result: **237 passed, 1 warning in 13.78s**, pytest exit 0.
Full output: baseline-pytest.txt.

RED:

```powershell
./.venv-vt015/Scripts/python.exe -m pytest -q query-api/tests/test_vt015_approval.py
```

Result: **14 failed, 8 passed, 1 warning in 5.90s**, pytest exit 1.
Full output: red-pytest.txt. All 14 failures are assertion failures:

- Four reviewer reads expect 200 but receive 401: current JWT validation only accepts admin.
- Approval permission, invalid/expired JWT, duplicate, storage failure and payload
  rejection cases receive 404 because the approval routes are absent.
- Concurrent approval receives [404,404] instead of [201,409].
- Missing-cluster response is 404, but required cluster lookup was never called;
  this deliberately prevents the absent route from producing a false pass.

No import, collection, setup or teardown errors occurred. Four admin reads and
four forbidden mutation method checks passed, exercising the same fixture.
The warning is the installed FastAPI/Starlette TestClient httpx deprecation;
it does not prevent execution. No claim of real OpenSearch concurrency or SLO
validation is made; see ../decision-table.md for test-double limitations.

## Preservation and scope

Only test and VT-015 documentation/evidence files were authored. No production
implementation, existing test, or shared contract was changed by this phase.
No staging, commit, reset or discard command was run.

The pre-existing api-contract.md change is preserved in existing-contract.diff.
Before/after SHA256 both equal:
`6991AA03DFC314305A94F862E139772A81C12E2CB754D33492984250C0CD7018`.

git-diff-stat.txt only shows the pre-existing tracked contract edit (9 additions);
Git diff does not include untracked new files. git-status-short.txt shows those
new paths as well. The new artifacts are ../decision-table.md, this evidence
directory, and query-api/tests/test_vt015_approval.py.

Stopped at RED. No implementation patch has been generated.
