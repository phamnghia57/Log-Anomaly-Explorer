# VT-015 RED decision table

Baseline: `50a3af1a159253d9f4d414fb54a4a90b1c4eba4a`.
Branch `bt3/23001907-vt015` already existed and was checked out when work began;
no branch was created or reset. Existing contract edit is excluded from this work.

All cases below are in `query-api/tests/test_vt015_approval.py`.
Cases with multiple paths/roles/payloads expand through pytest parametrization.

| ID | Identity / condition | Action | Expected | Test function |
|---|---|---|---|---|
| D01 | reviewer, valid JWT | GET search | 200 | test_read_permissions |
| D02 | reviewer, valid JWT | GET clusters | 200 | test_read_permissions |
| D03 | reviewer, valid JWT | GET cluster | 200 | test_read_permissions |
| D04 | reviewer, valid JWT | GET history | 200 | test_read_permissions |
| D05 | reviewer, existing cluster, no approval | POST approval then GET approval | 201 then 200; actor from JWT, timestamp from server; one write | test_approval_permission_and_original_immutability |
| D06 | reviewer | PATCH/PUT/DELETE original cluster, PATCH search | 403 or 405; no original write | test_reviewer_cannot_modify_original_data |
| D07 | JWT signed with wrong key | POST approval | 401 before storage | test_invalid_or_expired_jwt_before_storage |
| D08 | expired JWT | POST approval | 401 before storage | test_invalid_or_expired_jwt_before_storage |
| D09 | already approved, different actor | POST approval | 409; preserve winner; one total write | test_duplicate_approval_preserves_winner |
| D10 | two reviewers, simultaneous start, same cluster | two POST approvals | exactly [201,409]; one stored document/write | test_two_concurrent_approvals_have_one_success_and_one_storage_write |
| D11 | reviewer, missing cluster | POST approval | 404 after actual cluster lookup; zero writes | test_missing_cluster_does_not_create_approval |
| D12 | reviewer, approval storage raises StorageError | POST approval | 503; zero writes | test_storage_failure_is_503_without_write |
| D13 | reviewer, body approved_by=admin | POST approval | 422; zero writes | test_actor_spoofing_and_original_data_payload_are_rejected |
| D14 | reviewer, body changes score/log_ids | POST approval | 422; originals unchanged | test_actor_spoofing_and_original_data_payload_are_rejected |
| D15 | admin, valid JWT | four existing GET endpoints | 200 | test_read_permissions |
| D16 | admin, existing cluster | POST then GET approval | 201 then 200; originals unchanged | test_approval_permission_and_original_immutability |

## Test boundary and proposed seam

Tests import only existing production modules, use existing `admin_auth` configuration,
and sign reviewer tokens with real PyJWT. They do not bypass authentication dependencies.
No production route is registered by the tests.

The proposed test seam is `app.state.approval_repository` with `get(cluster_id)` and
`create(document) -> bool`: True means created, False means duplicate. StorageError
means unavailable. This is a proposed local repository interface, not an existing
shared contract. Response for GET approval is the stored approval document.

The lock in ApprovalDouble only makes the test double atomic. The concurrent API test
checks orchestration, response outcomes, and exactly one successful persistence write;
it does not establish real OpenSearch atomicity or multi-process correctness. Those
require later tests against the production repository and a real OpenSearch instance.
Two create attempts are legitimate; two successful persistence writes are not.

Original-data assertions check allowed read calls and returned original values. They
do not claim database ACL enforcement. Existing unsupported mutation routes may
already pass with 405; those are regression guards rather than new functionality.

No reviewer login/seed implementation, production files, shared contracts, load-test
implementation, or implementation patch is included in this RED slice. The reviewer
tokens here isolate authorization and approval behavior from provisioning.
