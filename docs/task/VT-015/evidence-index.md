# VT-015 evidence index

All paths below are relative to this directory. Historical artifacts are preserved,
including failures and limitations; newer results do not erase earlier evidence.
The concise reproduction guide is [README.md](README.md).

## Revision ledger

| Revision | Purpose / provenance |
|---|---|
| `50a3af1a159253d9f4d414fb54a4a90b1c4eba4a` | Existing baseline before VT-015: 237 query-api tests passed |
| `a4f13a37942606572f98c70fe5df05bedd7d0868` | RED tests, decision table, baseline/RED evidence; 14 failed, 8 passed |
| `e0c5a4f2600e562bf0e465df300c178b912842d7` | GREEN reviewer access and atomic approval implementation |
| `b627243c1f71a9417b581b2bc9e09a3f3a935a85` | Mutation evidence, state-isolation repair and shuffled/repeat checks |
| `0ae83dc5c70dab310fe78d6d31ff7aae66db2342` | Coverage tooling/tests and simulated HTTP concurrency/performance; 274 tests passed |
| Submission setup/documentation commit | Contains setup command, schema alignment, 24 setup tests, these documents and final 298-test evidence. Resolve exact hash with `git log -1 --format=%H -- query-api/src/setup_reviewer.py` |

The final hash is also reported in the delivery message. A self-contained commit
cannot store its own computed hash inside itself; the tracked setup-file addition
is the reproducible revision identifier for this last row.

## Final submission evidence

| Artifact | What it demonstrates / boundary |
|---|---|
| [submission-setup-review.md](evidence/submission-setup-review.md) | Actual provisioning/index-init audit; scope and limitations of the new setup |
| [submission-setup-pytest.txt](evidence/submission-setup-pytest.txt) | 24 setup tests passed using a stateful OpenSearch client double |
| [submission-pytest.txt](evidence/submission-pytest.txt) | Complete final query-api run: 298 passed; six-module branch coverage; full command and exit |
| [submission-coverage.json](evidence/submission-coverage.json) | Final executed/missing lines and arcs for auth, tokens, main, approvals, users and setup |
| [submission-coverage.data](evidence/submission-coverage.data) | Raw final coverage database; separate from historical coverage.data |
| [submission-doc-checks.txt](evidence/submission-doc-checks.txt) | Local documentation links and reflection word count |
| [submission-audit.txt](evidence/submission-audit.txt) | Branch/status/diff checks, staged scope and unchanged API contract hash |

## RED and GREEN

| Artifact | Purpose |
|---|---|
| [decision-table.md](decision-table.md) | RED acceptance/risk cases and injection-seam boundary |
| [baseline-pytest.txt](evidence/baseline-pytest.txt) | 237 baseline tests passed |
| [red-pytest.txt](evidence/red-pytest.txt) | Full 14-failed/8-passed RED output |
| [GREEN-review.md](evidence/GREEN-review.md) | Production file explanations and GREEN limitations |
| [green-vt015-pytest.txt](evidence/green-vt015-pytest.txt) | 22 RED-contract tests passed after implementation |
| [green-existing-pytest.txt](evidence/green-existing-pytest.txt) | Existing suite remained 237 passing |
| [green-auth-admin-pytest.txt](evidence/green-auth-admin-pytest.txt) | 181 focused regression checks passed |
| [green-patch.diff](evidence/green-patch.diff) | Historical GREEN source/test patch |
| [red-commit.txt](evidence/red-commit.txt), [green-commit.txt](evidence/green-commit.txt) | Recorded full RED/GREEN revision IDs |

## Mutation and flaky-test review

| Artifact | Purpose / result |
|---|---|
| [PATCH-mutation-review.md](evidence/PATCH-mutation-review.md) | Complete mutation interpretation, risk review and accept/modify/reject findings |
| [mutation.patch](evidence/mutation.patch) | Deliberately defective overwrite patch, evidence only |
| [mutation-pytest.txt](evidence/mutation-pytest.txt) | 1 failed, 26 passed; detector uses mocked-client contract, not a distributed race |
| [concurrency-repeats.txt](evidence/concurrency-repeats.txt) | Atomic approval double passed ten independent process runs |
| [shared-state-shuffled-pytest.txt](evidence/shared-state-shuffled-pytest.txt) | Original shuffled suite: 258 passed and six setup errors |
| [shared-state-minimal-before.txt](evidence/shared-state-minimal-before.txt) | Two-test reproduction: one passed and one setup error |
| [shared-state-minimal-after.txt](evidence/shared-state-minimal-after.txt) | Same sequence after fixture fix: two passed |
| [shared-state-shuffled-after.txt](evidence/shared-state-shuffled-after.txt) | Historical shuffled suite after repair: 264 passed |
| [shuffled_suite.py](evidence/shuffled_suite.py) | Reproducible collection shuffle seed 15015 |

## Coverage, backend availability and performance

| Artifact | Purpose / boundary |
|---|---|
| [COVERAGE-concurrency-performance.md](evidence/COVERAGE-concurrency-performance.md) | Four-module coverage/risk report and workload methodology at `0ae83dc` |
| [coverage-initial.txt](evidence/coverage-initial.txt), [JSON](evidence/coverage-initial.json) | Initial measured gaps before ten focused tests |
| [coverage-final.txt](evidence/coverage-final.txt), [JSON](evidence/coverage-final.json), [data](evidence/coverage.data) | Historical 274-test four-module measurement; not the new setup coverage |
| [coverage-workload-packages.txt](evidence/coverage-workload-packages.txt) | Resolved coverage/API/load-client package versions |
| [docker-info-approved.txt](evidence/docker-info-approved.txt), [containers](evidence/docker-containers-approved.txt) | Docker CLI available, daemon unavailable |
| [opensearch-probe.json](evidence/opensearch-probe.json) | HTTP/HTTPS localhost:9200 refused connections; no proof about remote services |
| [hardware.txt](evidence/hardware.txt) | i5-6300U, two cores/four logical processors, approximately 8 GB RAM |
| [workload-summary.md](evidence/workload-summary.md) | Standalone local simulation: counts and p50/p95/p99/max, success/conflict split |
| [workload-raw.csv](evidence/workload-raw.csv) | 162 per-request monotonic HTTP latency/status/error measurements |
| [workload-results.json](evidence/workload-results.json) | Backend/process metadata, invariants and nearest-rank percentiles |
| [workload-persisted.json](evidence/workload-persisted.json) | 82 unique synthetic persisted approval documents |
| [workload-validation.txt](evidence/workload-validation.txt) | Independent CSV percentile/count/persistence recomputation |
| [workload-command.txt](evidence/workload-command.txt), [server](evidence/workload-server.txt) | Executed workload command, exit and server output |
| [workload-initial/README.md](evidence/workload-initial/README.md) | Preserved first workload with coverage running alongside; excluded from final latency conclusion |

## Preservation and authorship

- [traceability matrix](traceability-matrix.md): acceptance criteria to evidence/revisions.
- [AI usage log](ai-usage-log.md): actual AI assistance and review decisions.
- [reflection draft](personal-reflection-vi.md): Vietnamese draft for student verification.
- [existing-contract.diff](evidence/existing-contract.diff): original unrelated contract edit;
  original/current SHA256 is `6991AA03DFC314305A94F862E139772A81C12E2CB754D33492984250C0CD7018`.
- Environment failure/install logs, intermediate coverage reports and prior audit
  snapshots remain in evidence/ for completeness. They are not substituted for the
  final successful runs.

No PDF, push, merge, PR, live OpenSearch concurrency test or production performance
claim is included. Existing commits and evidence remain intact.
