# VT-015 coverage, simulated concurrency and performance

Baseline for this continuation: `b627243c1f71a9417b581b2bc9e09a3f3a935a85` on `bt3/23001907-vt015`.
Production modules and all existing test expectations remain unchanged. Ten focused tests were added;
final all-query-api suite result is **274 passed, 1 existing warning**, exit 0. The final coverage
run also serves as the complete final test-suite verification after the standalone workload.

## Coverage

Installed pytest-cov 7.1.0 and coverage 7.17.1 into the existing `.venv-vt015` environment.
The sandbox network attempt failed; an approved retry installed both packages. Package versions
are recorded in coverage-workload-packages.txt; requirements files were not modified.
Full commands/output and machine-readable covered/missing arcs: coverage-initial.txt/json and
coverage-final.txt/json. coverage.data is the final raw branch coverage database.

The line column below counts executed statements only; it is not the combined line+branch
percentage shown in pytest-cov's terminal Cover column.

| Module | Initial line | Initial branch | Final line | Final branch |
|---|---:|---:|---:|---:|
| approvals.py | 96.15% | 100.00% | 100.00% (26/26) | 100.00% (4/4) |
| auth.py | 100.00% | 100.00% | 100.00% (66/66) | 100.00% (8/8) |
| main.py | 93.38% | 75.00% | 95.59% (130/136) | 85.71% (24/28) |
| tokens.py | 94.29% | 87.50% | 97.14% (34/35) | 100.00% (8/8) |

Focused tests in `query-api/tests/test_vt015_coverage.py` cover approval authentication before
storage access, missing repository 503 for GET/POST, missing cluster GET 404 without a repository
call, missing approval 404 versus unavailable read 503, successful/found-false production
repository reads, unsupported issued roles, and malformed/non-finite expiry claims.
All approval-route decision branches and repository create/conflict/failure outcomes are now
covered locally. Coverage percentages alone do not establish concurrency correctness.

### Remaining uncovered source and branches

- `main.py::_build_conversation_repository`: lines 108-110, arc 106->108 (successful Assistant OpenSearch bootstrap).
- `main.py::_parse_dt`: line 152, arc 151->152 (naive datetime interpreted as UTC).
- `main.py::list_clusters`: arc 214->217 (explicit since bypasses the default window).
- `main.py::get_cluster_history`: arc 270->273 (explicit since); lines 275-276 (history ValueError to HTTP 400).
- `tokens.py::decode_access_token`: line 52, defensive conversion of a decoder TypeError/ValueError/OverflowError.
  The concrete malformed expiry inputs are rejected by the installed PyJWT before reaching that fallback.
  All eight measured token branch arcs are covered; coverage does not count exception handlers as branch arcs.
- `auth.py` and `approvals.py`: no missing lines or branch arcs.

These remaining main.py paths are outside the new approval authorization/concurrency slice.
No production changes or artificial decoder mocks were introduced just to raise percentages.

## Backend availability and isolation

Docker CLI is installed but its daemon pipe is absent, including on the approved unsandboxed
check (docker-info-approved.txt / docker-containers-approved.txt). Both HTTP and HTTPS probes
to 127.0.0.1:9200 were refused (opensearch-probe.json). This establishes local default endpoint
unavailability, not absence of every possible remote or differently configured OpenSearch service.
No Docker services were started, and no production endpoint or index was written or deleted.

Used a clearly labeled **SIMULATED SQLite backend**, not OpenSearch. The actual production
ApprovalRepository executes its create-only persistence call against SQLiteApprovalClient,
whose transactional INSERT uses a database unique constraint. No Python lock arbitrates writes.
The simulator maps duplicate primary keys to the OpenSearch ConflictError type expected by
ApprovalRepository. It does not model transport, refresh, shards, replication or OpenSearch ACLs.
The index namespace starts `vt015-sim-`; the SQLite database lives in a TemporaryDirectory
and is removed after validation. Cluster existence reads use an isolated in-memory fixture.

## Concurrency and performance

Reproduce from repository root:

```powershell
./.venv-vt015/Scripts/python.exe query-api/tests/vt015_workload.py
```

One separate Uvicorn API process receives real loopback TCP HTTP requests from the load
generator on the same machine. Each batch starts 2 or 80 client threads with a barrier.
The 80-task measurements include HTTP connection/pool and server queueing. Monotonic
`time.perf_counter_ns` starts after the barrier and stops after receiving the full response.
Percentiles use nearest rank. API startup and the health-only readiness probe are excluded.
No approval warm-up requests are sent. Hardware: Intel Core i5-6300U @ 2.40 GHz, 2 cores,
4 logical processors, 8,476,332,032 bytes RAM; see hardware.txt. Python 3.13.7 / SQLite 3.50.4.

| Scenario | Tasks/requests | 201 | 409 | Persisted documents | Errors |
|---|---:|---:|---:|---:|---:|
| same_cluster_2 | 2 | 1 | 1 | 1 | 0 |
| same_cluster_80 | 80 | 1 | 79 | 1 | 0 |
| independent_clusters_80 | 80 | 80 | 0 | 80 | 0 |

Totals: 162 requests; 82 successes; 80 conflicts; 0 errors; 82 stored approvals.

| 80-task scenario | Response | Sample size | p95 seconds | Below 2.5 seconds |
|---|---|---:|---:|---|
| same_cluster_80 | success | 1 | 0.143714 | True |
| same_cluster_80 | conflict | 79 | 0.827589 | True |
| independent_clusters_80 | success | 80 | 1.470743 | True |

The single same-cluster winner is only one sample and has no useful percentile distribution.
Raw per-request latency/status/error data: workload-raw.csv. All p50/p95/p99/max measurements:
workload-summary.md. Full machine-readable configuration/results: workload-results.json.
Synthetic persisted documents: workload-persisted.json. API log: workload-server.txt.
workload-command.txt records command and successful exit. The initial workload ran alongside
coverage and is preserved separately in workload-initial/. Only the standalone parent-directory
workload is used for the final performance conclusion.

CSV validation recomputed each status/scenario percentile and verified status counts and
persistence totals; workload-validation.txt records that check.

## Final review and limitations

- The submission contains new VT-015 tests, the simulator/workload harness and evidence only.
  Existing production code and RED tests are unchanged from the previous commits.
- Remaining coverage arcs, exception-path gaps and deployment prerequisites are documented above.
- SQLite transactional uniqueness plus the real API/repository verifies the simulated adapter path.
  It does not verify actual OpenSearch concurrency, replication, refresh timing, network failures,
  multi-process API behavior, real cluster-data reads, or production performance.
- One batch per workload scenario is a small sample, particularly the single winning contender.
  Same-host hardware and background OS activity limit reproducibility of exact latency values.
- Both measured 80-task response groups meet the 2.5-second p95 comparison locally. This is
  not evidence of a production SLO.
- The unrelated api-contract.md SHA256 remains
  `6991AA03DFC314305A94F862E139772A81C12E2CB754D33492984250C0CD7018`.
- No prior evidence/commit was removed or rewritten. No push, merge or PR was performed.
- Final source/preservation checks are recorded in coverage-workload-audit.txt.
