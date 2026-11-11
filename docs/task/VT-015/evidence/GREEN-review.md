# VT-015 GREEN review

RED commit: `a4f13a37942606572f98c70fe5df05bedd7d0868`.
GREEN changes are left uncommitted for human review. RED expectations are unchanged.

## Production patch

- `query-api/src/tokens.py`: issue and validate admin/reviewer JWTs, preserving
  signature, expiry, subject and algorithm validation and the default admin role.
- `query-api/src/auth.py`: authenticate both supported roles, issue the stored
  user's role at login, and retain a separate admin dependency for Assistant.
- `query-api/src/main.py`: permit reviewer reads on the four existing query
  routes; wire the approval repository and add POST/GET approval routes. Check
  cluster existence, reject extra payload fields, derive actor/time on the server,
  return 201 only after confirmed creation, 409 for duplicates, 404 for absent
  clusters/approvals, and 503 through the existing StorageError handler.
- `query-api/src/approvals.py` (new): use the separate `cluster-approvals` index.
  OpenSearch `create` uses the cluster ID as its document ID; no index/update or
  original-data write is performed. Conflicts return False; unconfirmed writes,
  connection errors and missing-index reads raise StorageError.

Tracked production diff: 64 insertions, 13 deletions across three existing files;
the new repository is 37 lines. Full patch including supplemental tests is in
`green-patch.diff`. `git diff --check` passed. The pre-existing contract edit is
excluded; SHA256 remains
`6991AA03DFC314305A94F862E139772A81C12E2CB754D33492984250C0CD7018`.

## Verification

Commands run with `./.venv-vt015/Scripts/python.exe -m pytest -q`:

| Scope / arguments | Before | GREEN | Complete log |
|---|---|---|---|
| `query-api/tests/test_vt015_approval.py` | 14 failed, 8 passed | 22 passed | green-vt015-pytest.txt |
| `query-api/tests --ignore=query-api/tests/test_vt015_approval.py` (before adding supplemental tests) | 237 passed | 237 passed | green-existing-pytest.txt |
| `query-api/tests/test_vt015_green_regression.py query-api/tests/test_query_auth.py query-api/tests/test_auth_config.py query-api/tests/test_auth_integration.py query-api/tests/test_admin_login.py query-api/tests/test_admin_seeding.py` | supplemental tests new | 181 passed | green-auth-admin-pytest.txt |

All commands exited 0. One existing Starlette/httpx deprecation warning per run.
Supplemental tests cover reviewer password login and Assistant denial, production
repository create-only parameters, conflict handling, unconfirmed/timeout writes,
and missing-document versus unavailable-index reads. No test failures required
changing expectations. Existing tests and committed RED tests were not edited.

## Boundaries and assumptions

- Real OpenSearch concurrency was **not executed**. Concurrent API behavior uses
  the RED atomic double; repository calls use a mocked OpenSearch client.
- Deployment must provision the approvals index or permit OpenSearch index auto
  creation. Explicit mappings, index provisioning and database ACLs are not added.
- Reviewer accounts must already exist in the users index with a password hash
  and role `reviewer`; no reviewer seed/provisioning interface is added.
- Permission is role-wide over the existing query routes; no tenant/per-cluster
  ACL exists in this slice. Original data is protected by available API operations,
  not by new database credentials or ACLs.
- Cluster lookup and approval create are not a cross-index transaction. Concurrent
  cluster deletion is not covered. A transport timeout may leave an approval
  persisted even though the API returns 503; it never reports an unconfirmed 201.
- Approval index retention/mapping and live infrastructure behavior are unverified.

No mutation testing, merge, push or PR creation was performed. Stop for human review.
