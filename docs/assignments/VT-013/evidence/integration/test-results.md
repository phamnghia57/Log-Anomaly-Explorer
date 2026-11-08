# Executed integration results

Final runs: host real-server 13/13; host regressions 90/90; Python 3.11 real-server plus regressions 103/103. All exited 0.

The 13 integration cases below ran in both Python environments. Assertions query actual persisted OpenSearch documents. These are not additional unique cases each time.

## I-01 / AC-01 — test_i01_create_send_undo_get

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Second completed Send was undone to the first completed turn; GET and raw source/version matched.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i01_create_send_undo_get`.

## I-02 / AC-01 — test_i02_restore_exact_tool_history

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Unicode, null/empty content, ordered tool messages, tool-call fields and timestamps restored exactly; creation time retained.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i02_restore_exact_tool_history`.

## I-03 / T-03 / AC-01,03 — test_i03_first_send_restores_persisted_empty

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: First Send restored to persisted []; revision advanced; stale/repeated Undo returned 409 with no further write.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i03_first_send_restores_persisted_empty`.

## I-04 / AC-01 — test_i04_restart_api_process_recovers_restored_history

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Second OS process recovered the same restored response and raw document after the first process terminated.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i04_restart_api_process_recovers_restored_history`.

## I-05 / T-14 / AC-05 — test_i05_concurrent_sends_have_one_commit[create-only]

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Both requests read the same baseline; one 200 and one 409; only winner history and its exact snapshot persisted.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i05_concurrent_sends_have_one_commit[create-only]`.

## I-05 / T-14 / AC-05 — test_i05_concurrent_sends_have_one_commit[conditional-update]

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Both requests read the same baseline; one 200 and one 409; only winner history and its exact snapshot persisted.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i05_concurrent_sends_have_one_commit[conditional-update]`.

## I-06 / T-15 / AC-05 — test_i06_concurrent_undos_have_one_commit

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Two synchronized real reads yielded one successful Undo, one 409, one version advance and a consumed snapshot.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i06_concurrent_undos_have_one_commit`.

## I-07 / T-12 / AC-04 — test_i07_missing_document_versus_missing_index

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Actual SDK 404 shapes classified correctly; absent document valid, absent index StorageError/HTTP 503; no generation/write.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i07_missing_document_versus_missing_index`.

## I-08 / T-18 / AC-01,04 — test_i08_existing_strict_mapping_is_upgraded_additively

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Startup added undo only, kept legacy source/version and mapping fields; unexpected root field still rejected with server 400.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i08_existing_strict_mapping_is_upgraded_additively`.

## I-09 / AC-01,03 — test_i09_legacy_document_remains_readable

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Legacy history read with real revision/no Undo; current-token Undo returned nothing_to_undo without data/version changes.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i09_legacy_document_remains_readable`.

## I-10 / T-11 / AC-04 — test_i10_real_connection_failure_propagates_without_data_loss

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Real SDK connection refusal returned HTTP 503 before generation; original source/version unchanged.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i10_real_connection_failure_propagates_without_data_loss`.

## I-11 / T-13 / AC-04 — test_i11_real_write_rejection_preserves_snapshot

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: Actual index write block caused Undo HTTP 503; all pre-write history, version and recovery data retained.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i11_real_write_rejection_preserves_snapshot`.

## I-12 / T-06,07,08,19 / AC-02,03 — test_i12_validation_and_admin_auth_remain_enforced

- Host Python 3.14.6: **PASS**; Docker Python 3.11.18: **PASS**.
- Actual asserted behavior: GET/Send/Undo enforced real JWT; invalid boundaries 422 with no side effects; 1 and 4000 Unicode-code-point messages persisted.
- Source: `query-api/tests/test_assistant_undo_integration.py::test_i12_validation_and_admin_auth_remain_enforced`.

## Existing regressions

All 90 existing cases passed on both host and Python 3.11. Their exact node IDs, durations and results are in `backend-regression.junit.xml` and `python311-tests.junit.xml`; no existing assertion was modified.

One existing Starlette TestClient deprecation warning was retained. The initial harness failure is documented separately in README.md and initial-attempt/. No final skip or collection error is counted as a pass.
