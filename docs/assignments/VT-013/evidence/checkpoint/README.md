# VT-013 backend and integration checkpoint

This checkpoint is explicitly authorized after the GREEN and real OpenSearch
VERIFY review. It contains the Assistant Undo backend, contract documentation,
associated tests and a curated evidence subset. It does not contain frontend,
mutation, performance, issue #73 or unrelated local work.

Before staging, the VT-013 worktree was on `feat/vt013-undo-manhpd` at
`4487c1d93c77c117b1c18c0f611cd76152e3a011`. The separate `dev/manhpd` worktree
at `D:/SE/LAE-issue-73` was clean, at
`6ac9afe9c1d79fa94c10439a60417ff286658388`. It was inspected read-only.
Production, test and runner hashes matched the recorded GREEN/integration runs.
No branch switch, merge or cherry-pick is part of this checkpoint.

`manifest.json` lists every explicitly selected file and its working-tree byte
SHA-256, except the manifest itself to avoid a recursive self-hash. Git may
normalize CRLF to LF while staging; the manifest labels these as working-tree
hashes, not hashes of Git blob contents. The resulting commit hash is reported
after creation and binds the final staged tree, including this manifest.

The recorded executions remain 13/13 host real-server integration tests, 90/90
host backend tests and 103/103 Python 3.11 cases (13 real-server plus the same 90
regressions), along with Docker build/schema probe PASS. These results are from
VERIFY, not a newly claimed rerun during checkpoint preparation. No production or
test source is changed for this commit. Only evidence documentation is clarified.

The selected evidence was inspected for credentials/private-key/token patterns,
binary/generated outputs and non-test data. Preserved documents are the fixed
VT-013 fixtures in test-specific indexes on the disposable owned instance. No
JWT/password issued at runtime or project `.env` file is selected. This is a
targeted automated and manual review, not a guarantee about every possible secret
format. Check commands and findings are summarized in the manifest.

Verbose OpenSearch server logs, empty API logs, generation event dumps, duplicate
initial diagnostic artifacts and repeated local diff-audit reports remain local
and untracked. Unrelated files and Graphify output are not selected. The runner,
failure provenance, final logs/JUnit, persisted synthetic states, mappings,
versions, Docker packaging proof and ownership/cleanup evidence are retained.

Remaining limitations are unchanged: no frontend, mutation or 60-task performance
verification; no OpenSearch TLS/failover or lost-response experiment; real mixed
Send/Undo remains outside this integration slice. See `../integration/review.md`.
