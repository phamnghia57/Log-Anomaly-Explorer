# Proposed pull request (not created)

Base: `main`  
Head: `bt3/23001907-vt015`  
Published head: `15bbd209de9a3e2b7f892d31798bd62924c63d72`  
Branch: https://github.com/phamnghia57/Log-Anomaly-Explorer/tree/bt3/23001907-vt015

The base is GitHub's verified default branch. At preparation, main was
`836e0dfc34b7b4308cabef83047eb9aa57ad7d88`; merge-base was
`50a3af1a159253d9f4d414fb54a4a90b1c4eba4a`. Main has 11 commits and the head
has 5 commits beyond that common ancestor. No merge/rebase or combined-base test
has been performed. No PR has been created; the text below requires approval.

## Title

VT-015: add reviewer access and atomic cluster approvals

## Description

Reviewers can log in, read query/cluster/history data, and approve an existing
cluster. Admin access is preserved and Assistant remains admin-only. Approval
POST/GET routes use separate storage, server-controlled identity/time, and atomic
create-only persistence keyed by cluster ID: 201 for the winner, 409 for duplicates,
404 for missing clusters, and 503 for unavailable/unconfirmed storage. Explicit
setup provisions reviewers and initializes the approvals index without replacing
existing accounts or original incident data.

Validation and submission evidence:

- RED: 14 failed/8 passed; GREEN: 22 VT-015 tests passed. Final query-api suite:
  **298 passed**, including 24 setup tests.
- Overwrite mutation detected by the mocked-client repository contract test
  (1 failed/26 passed), not a real OpenSearch race. A shared-state fixture defect
  was reproduced and fixed; historical shuffled suite: 264 passed; concurrency
  double repetitions: 10/10 passed.
- Latest line/branch coverage: auth 100%/100%, approvals 100%/100%, tokens
  97.14%/100%, main 95.59%/85.71%, users 93.94%/87.50%, setup 97.22%/87.50%.
- **Simulated SQLite-backed HTTP workload**, one API subprocess: 2/80 same-ID
  contenders each produced exactly one 201/document; 80 distinct IDs all succeeded.
  At 80 tasks, independent-success p95 was 1.471 s and conflict p95 was 0.828 s,
  below 2.5 s locally. Raw CSV, coverage and traceability are under docs/task/VT-015.

Limitations: live OpenSearch provisioning/concurrency and production performance
were not verified; SQLite results do not establish a production SLO. Permissions
are role-wide; cluster lookup/create is not a cross-index transaction. Existing
incompatible mappings are preserved. Tests cover the head branch, not its
combination with the 11 newer main commits. The unrelated uncommitted API contract
edit is excluded from all five VT-015 commits.
