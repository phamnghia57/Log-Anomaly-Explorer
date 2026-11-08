# VT-013 GREEN — minimal backend verification

## Scope and actual result

- Branch: `feat/vt013-undo-manhpd`; HEAD before the patch: `4487c1d93c77c117b1c18c0f611cd76152e3a011`.
- Original production baseline: `a2e0c070d694054001767979fe3f247e7ebff6be`.
- The approved `plan.md` and the entire original RED assertion file are unchanged.
- Final results: **14 focused contracts passed**, **24 Assistant regressions passed**, **52 additional backend checks passed**. Each pytest process exited 0.
- A combined process ran the same **90 unique cases** together and also passed all 90, checking shared fixture restoration. This is a second execution of those cases, not 90 additional unique tests.
- No frontend, unrelated service, dependency declaration, RED evidence, commit or branch was changed. No dependency was installed, and no commit, push or PR was created.

The complete per-case mapping of test ID, result, actual asserted behavior and relevant implementation is in [test-results.md](test-results.md). Commands, versions, source/spec/test hashes and machine-readable results are in [results.json](results.json).

## Backend changes reviewed

### Request and response contracts

`ChatRequest` uses a strict string, rejects extra fields, checks length 1–4000 and rejects whitespace-only text without altering accepted text. `UndoRequest` accepts only a canonical ASCII `<primary_term>:<seq_no>` token with signed-64-bit bounds; sequence zero is valid. Validation failures are 422 before repository access.

GET and Send now return `cluster_id`, `messages`, `revision` and `undo_available`. Undo uses the same projection; recovery data is never exposed. Router-level admin authentication remains in place. Undo does not require Azure configuration or call generation/tools.

### Persistence and error paths

`ConversationState` carries the document and OpenSearch sequence/primary-term metadata separately. Reads validate stored data and metadata. Only a genuine document-not-found outcome means absence; missing indexes, malformed metadata and transport errors raise sanitized `StorageError`, preserving the existing HTTP 503 envelope.

There are exactly two persistence branches in `ConversationRepository._write()`:

1. No previously read document: `client.create(..., refresh="wait_for")`, which is create-only.
2. Existing document: `client.index(..., if_seq_no=previous.seq_no, if_primary_term=previous.primary_term, refresh="wait_for")`.

There is no unconditional update fallback. Typed `ConflictError` is handled before the generic storage exception path, producing `ConversationConflict` and HTTP 409. A malformed post-write response is an error with uncertain commit outcome; the code does not invent a revision or explicitly retry/rebase the operation.

Send stores the completed history and one deep-copied previous-history snapshot in a single conditional document write. Undo checks revision before snapshot availability, restores the full saved message sequence, clears the snapshot and uses the same conditional write. It preserves conversation creation time and issues new modification time/version metadata. Caller changes cannot alias the saved document or snapshot.

### Strict mappings and packaging

The stored JSON schema gains an optional `undo` object/null field; the pre-existing message schema is reused via a local JSON reference. Valid legacy documents need no data rewrite and initially have no snapshot.

New indexes include `undo: {"type":"object","enabled":false}`. Existing indexes receive an additive `put_mapping` operation with acknowledgement checking, including the index-creation race path. No index is dropped or recreated. An incompatible mapping or unacknowledged update fails as `StorageError`.

Runtime validation uses the already declared JSON Schema dependency. Query API's Dockerfile now copies that one schema file into its expected runtime location; its Docker build context does not exclude the file. No new production dependency was added.

## Why existing test fixtures changed

The old API fake returned plain documents without version metadata. It was replaced with the actual repository using the versioned OpenSearch transport double. Seeded histories still exercise the existing API behaviors.

The old empty-response assertion gained the two fields required by the approved contract. Repository tests now pass an explicit previously read state and inspect `ConversationState.document` plus version metadata. The invalid dummy message timestamp `"x"` was replaced by an actual date-time because the published schema has always required date-time format. Creation-time preservation and persisted-state equality assertions remain; they were not removed.

The transport double gains only `indices.put_mapping`, which preserves existing mapping properties. It still allows unconditional overwrites and raises conflicts only for actual CAS/create-only arguments. The original focused RED tests, including all concurrency assertions, remain byte-for-byte unchanged.

## Results and files

| Group | Cases | Actual result | Exit status | Evidence |
|---|---:|---|---:|---|
| Focused RED contracts, unchanged | 14 | All pass | 0 | `focused-green.log`, `focused-green.junit.xml` |
| Existing Assistant API/repository regressions | 24 | All pass | 0 | `assistant-regression.log`, `assistant-regression.junit.xml` |
| Additional backend contracts | 52 | All pass | 0 | `backend-contracts.log`, `backend-contracts.junit.xml` |
| Combined backend run | 90 | All pass | 0 | `combined-backend.log`, `combined-backend.junit.xml` |

Additional checks cover exact Unicode/tool history restoration, one-level consumption, stale/malformed revisions, string/type/numeric boundaries, storage write failure, concurrent Undo/Undo and Undo/Send, mapping updates, legacy reads, authentication, corrupt snapshots, invalid metadata and deep-copy isolation. Real JWT verification and actual production routes/repository run in the tests; generation and the OpenSearch transport are test doubles.

### Diagnosed failure retained for review

The initial additional-check run had 51 passes and one failure in the new alias-isolation test. The test used `messages = history + turn("B")`, which shared message dictionaries with its expected `history`. Editing `messages[0]` therefore changed the expected value, while production correctly retained the original snapshot.

The correction was to prepare `messages = deepcopy(history) + turn("B")`. The same snapshot-equality assertions remain. Production was not changed to satisfy that failure; neither the approved specification nor the original RED assertions was relaxed.

The failed run is preserved as `backend-contracts-initial.log`, `backend-contracts-initial.junit.xml` and `initial-results.json`, including its original test-source hash and assertion details. Final logs are separate. This was a test-data setup correction, not a production mutation experiment.

## Reproduction

From the repository root, with the existing interpreter:

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B docs/assignments/VT-013/evidence/green/run_green.py
```

The final runner exits 0 only when all four groups complete successfully. It writes GREEN evidence only; it reuses the RED capture utility with its output directory redirected to `green`, never rewriting RED results. It regenerates the per-case report from final JUnit data.

Each subprocess runs from `D:\SE\Log-Anomaly-Explorer\query-api` with this prefix:

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B -m pytest -vv --tb=short -rA --color=no -p no:cacheprovider -o faulthandler_timeout=20
```

The exact complete argument arrays, including JUnit destinations and selected files, are in the log headers and `results.json`. Child environments use `STORAGE_BACKEND=memory`, disable OTLP export, Langfuse tracing, third-party pytest plugin autoload and bytecode/cache writes. Test fixtures supply their own non-production Azure configuration and signed JWTs; inherited Langfuse keys are removed from child environments.

Tests ran outside the Windows sandbox that previously blocked TestClient socketpair initialization. There were no test-collection, fixture, synchronization or dependency errors in final runs. The existing Starlette HTTPX deprecation warning remains; dependencies were not changed to suppress it.

## Review boundaries and remaining gaps

- OpenSearch is a transport double. Real OpenSearch 2.17.1 mapping updates, client/server interactions, persistence after restart and distributed conflicts remain integration-test gaps. This evidence does not establish the 60-task p95 target.
- The available interpreter is Python 3.14.6, with OpenSearch client 3.2.0 and Pydantic 2.14.3. CI's Python 3.11 environment was not executed here; exact installed versions are recorded.
- The Docker COPY source and runtime schema path were inspected, but no Docker image was built or deployed.
- Legacy readability assumes documents conform to the published message/date-time schema. Malformed historical data now fails closed with 503 rather than being silently repaired or replaced.
- Do not mix old unconditional writers with the new backend. Schema/index identity must remain stable during a conversation's version history; external index deletion/recreation is not a recovery mechanism.
- The repository adds no application-level mutation retries. The shared OpenSearch client's inherited transport retry policy is unchanged; uncertain post-commit timeout/retry outcomes still need a real integration test and client reconciliation through GET.
- No frontend, browser E2E, mutation experiment, coverage/flakiness campaign, performance run or automatic deployment was performed in this phase.

Stop after backend review. Further changes require the next user instruction.
