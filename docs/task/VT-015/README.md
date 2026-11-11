# BT3 - AI-06 - VT-015: reviewer approval

This directory is the academic submission source package. No PDF has been generated.
Start with [traceability](traceability-matrix.md), [AI usage](ai-usage-log.md),
[Vietnamese reflection draft](personal-reflection-vi.md), and the
[evidence index](evidence-index.md). Branch: `bt3/23001907-vt015`.

## Problem and scope

Allow an authenticated reviewer to read query/cluster data and approve an existing
cluster without changing original logs, clusters or history. Admin access remains
available; Assistant remains admin-only. Concurrent approval attempts for the same
cluster must have one winner (201), with duplicates returning 409. Approvals are
separate documents with a server-controlled actor and UTC timestamp.

The implementation uses JWT authentication, stored Argon2id password hashes, and
OpenSearch create-only persistence keyed by cluster ID. This submission also adds
explicit reviewer provisioning and approval-index initialization, plus isolated
tests and reproduction tools. It does not add public signup, tenant/object ACLs,
account editing, cluster deletion, approval revocation or a new UI.

## Environment and test setup

Run PowerShell commands from the repository root. The recorded interpreter is
Python 3.13.7. Tests run without OpenSearch; live login/setup requires OpenSearch.

```powershell
# Only create the venv if it does not already exist.
python -m venv .venv-vt015
./.venv-vt015/Scripts/python.exe -m pip install -r query-api/requirements-dev.txt
./.venv-vt015/Scripts/python.exe -m pip install pytest-cov==7.1.0 coverage==7.17.1
```

The existing venv was reused during the work. Resolved package versions are in
[coverage-workload-packages.txt](evidence/coverage-workload-packages.txt).

## Explicit live setup: reviewer and indexes

The earlier implementation could authenticate a stored reviewer, but only exposed
admin seeding; it relied on approval-index provisioning outside the application.
`query-api.src.setup_reviewer` now explicitly prepares the configured users index
and the fixed `cluster-approvals` index, then creates a reviewer using `_create`.
It does not call log-store initialization, write original data, change existing
mappings, reset passwords or convert existing roles. Repeated setup preserves
existing accounts; concurrent creates are resolved by OpenSearch conflicts.

Use a dedicated local test OpenSearch instance for reproduction, or the intended
deployment with operator authorization. These commands perform writes only when
you run them; they were **not executed against live OpenSearch** in this submission.
Docker daemon/default local OpenSearch were unavailable during verification.

```powershell
$env:STORAGE_BACKEND = "opensearch"
$env:OPENSEARCH_URL = "http://127.0.0.1:9200"
$env:USERS_INDEX = "vt015-submission-users"
$env:JWT_SECRET = & ./.venv-vt015/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:REVIEWER_SEED_USERNAME = "vt015-reviewer"
$reviewerPassword = Read-Host "Reviewer password" -AsSecureString
$reviewerCredential = [System.Management.Automation.PSCredential]::new("unused", $reviewerPassword)
$env:REVIEWER_SEED_PASSWORD = $reviewerCredential.GetNetworkCredential().Password
./.venv-vt015/Scripts/python.exe -m query-api.src.setup_reviewer
Remove-Item Env:REVIEWER_SEED_PASSWORD
```

Configure `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD` and `OPENSEARCH_VERIFY_CERTS`
as required by the actual instance. The setup credential needs index-creation and
document-read/create permissions. Runtime access should be restricted separately.
JWT_SECRET is required for login/API use (minimum 32 bytes); setup itself does not
issue a JWT and does not require it. No secrets should be committed or copied into
submission logs.

Expected setup exit code: 0 when created or an existing account is preserved;
1 on invalid credentials/configuration/storage failures. An existing **admin** with
the same username stays admin: choose a distinct reviewer username. Existing
incompatible index mappings are preserved and require operator review, not migration.

The users JSON schema now admits `admin` and `reviewer`; the OpenSearch role field
already accepts keyword values. Approval mapping is strict: `cluster_id` and
`approved_by` are keywords and `approved_at` is a date. The unrelated uncommitted
`docs/architect/contracts/api-contract.md` edit is excluded from this submission.

For an admin, the existing setup remains available:

```powershell
# Set ADMIN_SEED_USERNAME and ADMIN_SEED_PASSWORD securely first.
./.venv-vt015/Scripts/python.exe -m query-api.src.seed_admin
./.venv-vt015/Scripts/python.exe -m uvicorn query-api.src.main:app --host 127.0.0.1 --port 8002
```

Existing clusters/logs must be supplied by the normal ingestion/clustering pipeline;
reviewer setup does not create them. Use a valid existing cluster ID for live approval.

## API and permissions

| Endpoint | Reviewer | Admin | Behavior |
|---|---|---|---|
| `POST /auth/login` | Stored account/password | Stored account/password | Returns JWT with stored role; invalid credentials 401 |
| `GET /search` | Yes | Yes | Original log query |
| `GET /clusters` | Yes | Yes | Cluster list |
| `GET /clusters/{id}` | Yes | Yes | Cluster and related logs |
| `GET /clusters/{id}/history` | Yes | Yes | Read history |
| `POST /clusters/{id}/approval` | Yes | Yes | No body or `{}`; 201 on creation, 409 on duplicate |
| `GET /clusters/{id}/approval` | Yes | Yes | 200 document, 404 absent cluster/approval |
| `GET /assistant/clusters/{id}/conversation` | 403 | Yes | Assistant remains admin-only |
| `POST /assistant/clusters/{id}/conversation/messages` | 403 | Yes | Assistant remains admin-only |
| Original-data PATCH/PUT/DELETE routes | Unsupported | Unsupported | Existing unsupported methods return 405 |

Protected endpoints require `Authorization: Bearer <token>`; missing/invalid/expired
tokens return 401. Approval payload extras such as `approved_by`, score or log IDs
return 422. Storage unavailable/unconfirmed writes return 503. A transport timeout
can mean a write persisted despite a 503; the API does not falsely report a 201.

Example after starting the live API (password is entered interactively):

```powershell
$loginPassword = Read-Host "Reviewer password" -AsSecureString
$loginCredential = [System.Management.Automation.PSCredential]::new("unused", $loginPassword)
$loginBody = @{ username="vt015-reviewer"; password=$loginCredential.GetNetworkCredential().Password } | ConvertTo-Json
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/auth/login -ContentType application/json -Body $loginBody
$headers = @{ Authorization="Bearer $($session.token)" }
$clusterId = Read-Host "Existing cluster ID"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8002/clusters/$clusterId/approval" -Headers $headers
Invoke-RestMethod -Uri "http://127.0.0.1:8002/clusters/$clusterId/approval" -Headers $headers
```

## Tests and expected results

```powershell
./.venv-vt015/Scripts/python.exe -m pytest -q query-api/tests/test_vt015_approval.py
./.venv-vt015/Scripts/python.exe -m pytest -q query-api/tests/test_vt015_setup.py
./.venv-vt015/Scripts/python.exe -m pytest -q query-api/tests
```

Expected: **22 VT-015 RED-contract tests**, **24 setup tests**, and **298 total**
passing tests. The existing Starlette/httpx deprecation warning remains. The setup
tests use a stateful client double with real hashing, repositories and login/JWT
code; they are not live OpenSearch provisioning tests. Full final command/output:
[submission-pytest.txt](evidence/submission-pytest.txt).

## Mutation reproduction (isolated, deliberately defective)

The historical experiment replaced `_create` with overwrite `index()` and accepted
updated results. It produced **1 failed, 26 passed**: the production-repository
client-contract test detected it; all 22 injected RED API tests still passed.
See [mutation output](evidence/mutation-pytest.txt) and [review](evidence/PATCH-mutation-review.md).
Do not apply this patch to the submission branch. Reproduce in a detached worktree
at the exact GREEN revision, using the existing venv:

```powershell
$repoPath = (Resolve-Path .).Path
$mutationTree = Join-Path $env:TEMP "vt015-mutation-repro"
git worktree add --detach "$mutationTree" e0c5a4f2600e562bf0e465df300c178b912842d7
git -C "$mutationTree" apply "$repoPath/docs/task/VT-015/evidence/mutation.patch"
Push-Location "$mutationTree"
& "$repoPath/.venv-vt015/Scripts/python.exe" -m pytest -q query-api/tests/test_vt015_approval.py query-api/tests/test_vt015_green_regression.py
Pop-Location
# Only clean up the deliberately modified file in this disposable worktree.
git -C "$mutationTree" restore -- query-api/src/approvals.py
git worktree remove "$mutationTree"
```

The expected failure is a mocked-client call/response mismatch, not observation of
an actual concurrent OpenSearch overwrite. The historical mutation branch was
never merged; production still uses `client.create` and deterministic cluster IDs.

## Coverage, shuffled order and performance reproduction

Write fresh results to a new directory so historical evidence remains intact:

```powershell
$reproEvidence = "docs/task/VT-015/evidence/reproduction-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Path $reproEvidence | Out-Null
$env:COVERAGE_FILE = "$reproEvidence/coverage.data"
./.venv-vt015/Scripts/python.exe -m pytest -q query-api/tests --cov=query-api.src.auth --cov=query-api.src.tokens --cov=query-api.src.main --cov=query-api.src.approvals --cov=query-api.src.users --cov=query-api.src.setup_reviewer --cov-branch --cov-report=term-missing --cov-report="json:$reproEvidence/coverage.json"
./.venv-vt015/Scripts/python.exe docs/task/VT-015/evidence/shuffled_suite.py
# Run the workload after tests stop, without pytest running alongside it.
./.venv-vt015/Scripts/python.exe query-api/tests/vt015_workload.py --output "$reproEvidence/workload"
Remove-Item Env:COVERAGE_FILE
```

For the original four-module run at `0ae83dc`, line/branch coverage was auth
100%/100%, tokens 97.14%/100%, main 95.59%/85.71%, approvals 100%/100%.
These figures predate the setup additions. Current six-module coverage and missing
arcs are preserved in [submission-coverage.json](evidence/submission-coverage.json)
and the final test log. A high coverage percentage is not proof of correctness.

Historical standalone workload: 162 HTTP requests to one API subprocess. Same-ID
batches with 2/80 tasks each stored one approval and returned one 201 plus 1/79
conflicts. Eighty distinct IDs produced 80 successes and documents. Zero errors.
At 80 tasks, p95 was **1.471 s** for independent approvals and **0.828 s** for
conflicts, below the **2.5 s** comparison locally. Percentiles are nearest-rank and
use `perf_counter_ns` around each complete HTTP request. Raw CSV, p50/p95/p99/max,
hardware and methodology are in the [workload summary](evidence/workload-summary.md)
and [coverage/performance review](evidence/COVERAGE-concurrency-performance.md).
Exact timings are not guaranteed on reproduction; assert response/persistence counts.

## Explicit limitations

- SQLite simulation uses a real unique-key transaction and the actual repository,
  but does not implement OpenSearch shards, replication, refresh waits, transport,
  access controls, cluster failures or distributed durability.
- The API runs in a separate process over loopback HTTP, but load generation and
  API share one machine; cluster reads are fixtures. There is one batch per
  scenario, and the single winner has no useful latency distribution.
- Neither the concurrency results nor local p95 establishes a production SLO.
  Live OpenSearch provisioning, concurrency and end-to-end ingestion were not run.
- Permissions are role-wide; no per-cluster/tenant ACL or database credential
  separation is implemented. Cluster lookup and approval create are not a
  cross-index transaction; concurrent cluster deletion remains untested.
- Existing account/index configuration is preserved. Setup does not repair old
  incompatible mappings or change an existing user's role/password.
- Secret rotation, approval retention, revocation and operational deployment review
  remain outside this slice. The API contract edit is intentionally not committed.

The package is ready for source review and an authorized push after the final
checks; it is not a claim of production deployment readiness or academic approval.
