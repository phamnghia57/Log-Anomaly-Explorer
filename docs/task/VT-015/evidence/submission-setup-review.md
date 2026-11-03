# Submission setup audit and verified changes

## Gap observed in the actual flow

`auth.login` verifies a stored password and accepts admin/reviewer roles, and the
GREEN supplemental test can log in using a supplied reviewer document. However,
`seed_admin` only calls `UserRepository.create_admin`; there was no reviewer seed
command. `ApprovalRepository` only had create/get, so explicit index setup was also
missing. The users JSON schema still listed only admin even though the runtime
role field is an OpenSearch keyword. These are source-backed observations, not
inferences that any production deployment failed.

## Small setup slice

- `query-api/src/users.py`: add `create_reviewer`, using real Argon2id hashing,
  fixed reviewer role, UTC creation timestamp, deterministic username and atomic
  `client.create`. Return False on conflict, and raise sanitized StorageError on
  unavailable or unconfirmed persistence. Existing admin creation is unchanged.
- `query-api/src/approvals.py`: add explicit `ensure_ready` to create only
  `cluster-approvals` with strict mappings. Reuse configured index settings;
  require acknowledged creation; tolerate the specific concurrent already-exists
  race. Existing indexes/mappings/documents are not modified. Runtime approval
  `create` remains atomic; no overwrite, delete, upsert or startup side effect added.
- `query-api/src/setup_reviewer.py`: validate two explicit seed environment values
  before connecting, require the existing OpenSearch UserRepository backend,
  initialize users and approvals, preserve any existing account, and create a
  reviewer only when absent. Close owned connections on success/failure; preserve
  borrowed connections. CLI reports generic success/failure without printing secrets.
- `docs/architect/contracts/users-schema.json`: align title/description and role
  enum with the implemented admin/reviewer user records. This is a directly related
  schema correction, distinct from the preserved unrelated api-contract.md edit.

The setup command uses no public endpoint and accepts no caller-supplied role.
Provisioning is explicit; API startup does not automatically run the seed. A run
may create empty users/approval indexes before a later failure: no transactional
rollback across indexes is claimed. Existing account creation conflicts preserve
the winner, including a pre-existing admin role.

## Tests and actual results

`query-api/tests/test_vt015_setup.py` contains 24 expanded tests. The stateful
OpenSearch client double verifies real document construction, schema validity,
password hashing/verification, setup-to-login JWT role, existing-account
preservation, repeated setup, account/index create races, strict approval mapping,
failure/acknowledgement handling, credential validation before connection, backend
rejection, resource cleanup and sanitized CLI outcomes. A sentinel makes any
original log-store initialization fail the test. Client index/update/delete and
mapping-update operations are not used by the verified setup paths.

- Focused setup: **24 passed**, one existing warning; `submission-setup-pytest.txt`.
- Complete query-api suite after setup: **298 passed**, one existing warning;
  `submission-pytest.txt`, exit 0.
- Final six-module line/branch data: `submission-coverage.json`; original coverage
  measurements were retained under their original filenames.

This verifies provisioning logic against the client interface, not live OpenSearch
index creation. Docker/default local OpenSearch were unavailable in the preceding
availability check. No real account, index or original incident data was created,
changed or deleted during this preparation. Existing incompatible mappings and
live deployment privileges remain operator review items.

## Submission documents and preservation

README contains setup, roles, tests, safe mutation reproduction in a detached
worktree, and coverage/performance commands writing to fresh output directories.
Traceability, AI assistance, review findings, the Vietnamese reflection draft and
the evidence index refer to actual recorded work. Historical mutation and performance
results are not relabeled as new live results.

The source package is ready for review and an authorized push, subject to human
academic/authorship review and the documented infrastructure limitations. No PDF,
push, merge or PR was generated. See `submission-audit.txt` for final staged scope
and API contract preservation.
