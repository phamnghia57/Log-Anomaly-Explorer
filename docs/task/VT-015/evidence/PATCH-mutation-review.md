# VT-015 patch, mutation and risk review

## Commit and preservation audit

- RED: `a4f13a37942606572f98c70fe5df05bedd7d0868`.
- GREEN: `e0c5a4f2600e562bf0e465df300c178b912842d7`.
- Full production patch was inspected: auth.py, tokens.py, main.py and the new
  approvals.py; supplemental tests were also inspected. Production size is 101
  additions / 13 deletions. No unrelated production modules were changed.
- `git diff RED -- query-api/tests/test_vt015_approval.py` is empty.
- The unrelated API contract change was neither staged nor edited. SHA256 is still
  `6991AA03DFC314305A94F862E139772A81C12E2CB754D33492984250C0CD7018`.
- GREEN staging contained only VT-015 production, supplemental tests and evidence.
  `git diff --check` passed. Subsequent test isolation fixes are separate from GREEN.

Authorization review: tokens validate signatures, expiry and supported roles;
login derives role from stored users. `auth.require_admin` rejects reviewers with
403, and `main.py:122` applies it to Assistant. Existing query endpoints now admit
both supported roles. There is no per-cluster or tenant ACL in this slice.

Storage/concurrency review: `ApprovalRepository.create` uses the separate
`cluster-approvals` index and deterministic cluster ID with `client.create`.
Conflict returns False and API 409; other failures raise StorageError/API 503.
Only a confirmed `created` result yields 201. Server derives actor/time; the empty
payload model forbids extra fields. Original-data mutation routes were not added.
Cluster existence lookup and approval write are not a cross-index transaction.

Contract concerns: no reviewer provisioning endpoint, no explicit approvals-index
provisioning/mapping, and no deployment ACL changes. Index auto-creation or prior
provisioning is required. A missing index is treated as unavailable storage on GET,
while a missing approval document is 404. These decisions need human acceptance.

## Mutation experiment

Created `bt3/23001907-vt015-mutation` from the exact GREEN commit. Changed
`ApprovalRepository.create` from `client.create` to `client.index` and accepted
both `created` and `updated` results, removing overwrite protection. See
`mutation.patch` for the exact defective patch.

Command and complete output: `mutation-pytest.txt`. Ran both VT-015 test files:
**1 failed, 26 passed**, exit 1. Detector:
`test_vt015_green_regression.py::test_repository_uses_separate_index_and_create_only`.
It failed at `assert repository.create(document) is True`, raising StorageError.
The fixture configures a successful `client.create` response; the mutated `index`
call returns an unconfigured Mock and fails result validation. The test also
explicitly asserts the create parameters and that index/update were never called,
but execution did not reach those assertions in this experiment.

Interpretation: the mutation was killed by a repository API-contract test, not by
observing a lost concurrent approval. All 22 RED API tests still passed because
they inject ApprovalDouble. Timeout tests also still passed because generic Mock
results yield StorageError; that is not proof they exercised the intended timeout
under mutation. A stateful production-repository/API test remains useful future work.
The mutation did not survive, so no test strengthening/repeated mutation was required.

Restored approvals.py byte-for-byte from GREEN and switched back to
`bt3/23001907-vt015`. The mutation was never committed or merged; its branch points
at GREEN and the defective code is retained only as a patch evidence artifact.
`git diff GREEN -- query-api/src` is empty.

## Restoration and flaky-test investigation

1. Restored normal suite: **264 passed**, exit 0 (`restored-all-pytest.txt`).
2. Scheduling risk: repeated the RED concurrent approval test in ten independent
   Python processes. **10/10 passed**, each checks exactly [201,409] and one write.
   Complete commands/output are in `concurrency-repeats.txt`. The barrier aligns
   request starts, not storage arrival, and its 10-second timeout can fail on an
   overloaded runner. The lock in ApprovalDouble guarantees its own atomicity;
   repeated success cannot establish OpenSearch or multi-process correctness.
3. Shared-state risk: shuffled the entire suite with fixed seed 15015 using
   `shuffled_suite.py`. Initial result: **258 passed, 6 setup errors** in Assistant
   tests (`shared-state-shuffled-pytest.txt`). Minimal sequence reproduced it:
   reviewer-login supplemental test followed by Assistant empty conversation test
   gave **1 passed, 1 setup error** (`shared-state-minimal-before.txt`).
4. Actual cause: `test_reviewer_login_and_assistant_denial` used monkeypatch.setattr
   on Starlette State. Teardown deleted the existing assistant_conversations key.
   Existing test_assistant.py's clusters fixture already documents this State
   behavior. Replaced the two supplemental State attribute patches with
   monkeypatch.setitem on the backing dictionary, which restores prior key values.
   RED expectations and production were not changed. Minimal sequence now gives
   **2 passed** (`shared-state-minimal-after.txt`).

Final normal and shuffled reruns both passed **264 tests**, exit 0, recorded in
`final-all-pytest.txt` and `shared-state-shuffled-after.txt`. Each run has the existing Starlette/httpx
deprecation warning. No new production fixes were needed.

## Coverage and acceptance risk

Neither pytest-cov nor coverage is installed in the isolated test environment;
`coverage-availability.txt` records the check. The requested conditional line and
branch measurement could not be performed. No percentage is claimed and no
dependencies were added. Test counts are not a substitute for coverage metrics.

| Acceptance risk | Evidence | Boundary / gap |
|---|---|---|
| Reviewer authentication and reads | real signed JWTs in RED; real password login in supplemental | account provisioning external; no object ACL |
| Admin access and Assistant restriction | existing auth/admin/Assistant suite plus reviewer denial | live deployment auth not exercised |
| Original log/cluster/history immutability | allowed read-call assertions and unsupported mutation routes | no new database ACL enforcement |
| Server-controlled actor/time and payload rejection | RED approval/payload cases | repository accepts trusted internal documents |
| Missing clusters and unavailable writes | RED lookup/storage tests; repository failure cases | live connection failures not injected |
| Duplicate/concurrent approval | RED duplicate/concurrency; repository create/conflict test; mutation killed | RED bypasses production repository; real OpenSearch not run |
| Read approvals | RED round-trip; repository missing/error tests | production repository successful read not directly tested |
| No false successful persistence | confirmation check, empty response/timeout tests | transport timeout can mean persisted data with 503 |

## Independent AI review after verification

This is a separate reviewer pass by the same agent, not a second agent or human.

| Finding | Exact evidence | Recommendation and disposition |
|---|---|---|
| Confirmed test isolation defect in GREEN supplemental fixture | test_vt015_green_regression.py::test_reviewer_login_and_assistant_denial; initial setattr calls; minimal reproduction above; test_assistant.py::conversations reads the deleted key | **Accept**: fix only supplemental fixture using mapping patch; implemented and reverified. No production workaround. |
| Confirmed production repository coverage gap | test_vt015_approval.py::vt015 injects ApprovalDouble; test_two_concurrent_approvals_have_one_success_and_one_storage_write therefore does not use ApprovalRepository; mutation output shows 22 RED tests still passing | **Accept** as a limitation and future test recommendation: connect the production repository to a stateful client double and later real OpenSearch. Do not claim real concurrency validation from current tests. |
| Confirmed deployment prerequisite | approvals.py::ApprovalRepository.__init__ names index; create/get never provision it; main.py only constructs repository | **Modify** a recommendation to add automatic startup provisioning: first confirm deployment index policy, then choose explicit provisioning or documented auto-create. No unsolicited infrastructure change in this patch. |
| Plausible but unsupported claim: production approvals will fail because index auto-creation is disabled | approvals.py::create would surface such a denial as StorageError; no live index settings, credentials or deployment probe was collected | **Reject** as an established defect; retain as an unverified deployment assumption and request environment validation before asserting failure. |
| Plausible claim: reviewers can bypass Assistant authorization via its nested routes | main.py:122 includes the router with require_admin; auth.py::require_admin rejects reviewer; supplemental checks both nested paths | **Reject**: current source and executed tests support denial; no bypass evidence. |

No merge, push, PR, or live OpenSearch concurrency test was performed. Stop for
human review with the atomic implementation on the submission branch.
