# VT-013 — Undo Assistant Send: Specification and Implementation Plan

- **Project:** AI-06 — Log Anomaly Explorer
- **Team:** SE2026-T04
- **Assignment:** Individual Assignment 3 — VT-013
- **Branch:** `feat/vt013-undo-manhpd`
- **Baseline:** `a2e0c070d694054001767979fe3f247e7ebff6be`
- **Reviewed:** 2026-11-08, Asia/Saigon
- **Document:** `docs/assignments/VT-013/plan.md`

**Status:** Approved planning-document step only. This document records the specification and future implementation plan. Production code, tests, dependencies, commits and pushes are outside the current step. The executed evidence in Section 5 is distinct from the planned verification; no implementation test or performance pass is claimed.

All source references below identify the reviewed baseline, not the latest GitHub `main`. Repository-relative paths resolve from the repository root. Source links are pinned to the baseline commit so that later changes cannot silently move the evidence.

## 1. Specification, verified contracts and invariants

### Problem statement

Assistant Send logically appends a completed conversation turn, but persistence replaces the entire conversation document without a concurrency precondition. Competing requests can therefore overwrite a completed turn. Users also cannot reverse the latest completed Send. Add durable, one-level Undo and conditional persistence so that recovery restores the exact previous message history without overwriting intervening changes.

### Verified repository facts

| Area | Current behavior and source evidence |
|---|---|
| Send API | `POST /assistant/clusters/{cluster_id}/conversation/messages`, handled by `post_message()`. Request is `{"message": string}`; successful response is `200` with `cluster_id` and the entire saved `messages` array. [query-api/src/assistant/router.py:L63](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/router.py#L63) |
| Conversation read | `get_conversation()` returns `messages: []` when the cluster exists but no conversation is returned. Unknown cluster produces `404`. [query-api/src/assistant/router.py:L52](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/router.py#L52) |
| Persistence | One OpenSearch document per cluster, `_id = cluster_id`. `save()` replaces the complete document with `refresh="wait_for"`. It preserves `created_at` only when the caller supplies it. [query-api/src/assistant/storage.py:L61](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/storage.py#L61) |
| Request validation | `ChatRequest.message` has length 1–4000. There is no backend whitespace-only check or explicit extra-field rejection. [query-api/src/assistant/router.py:L24](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/router.py#L24) |
| Browser validation | `handleSend()` trims the draft and refuses an empty value or a second pending Send. This does not protect direct API calls or other browser sessions. [web/src/components/incident/AssistantPanel.tsx:L81](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/web/src/components/incident/AssistantPanel.tsx#L81) |
| Stored schema | Requires cluster ID, timestamps and messages; permits an empty message array and nullable content. Top-level additional properties are forbidden. [docs/architect/contracts/assistant-conversation-schema.json:L7](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/docs/architect/contracts/assistant-conversation-schema.json#L7) |
| Mapping | OpenSearch mapping is strict. `ensure_ready()` creates a missing index but does not update an existing mapping. [query-api/src/assistant/storage.py:L18](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/storage.py#L18), [ensure_ready():L41](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/storage.py#L41) |
| Storage errors | Repository client exceptions are wrapped as `StorageError`; the application handler returns `503` with `error` and `detail`. [query-api/src/assistant/storage.py:L53](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/storage.py#L53), [query-api/src/main.py:L129](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/main.py#L129) |
| Missing-index ambiguity | `get()` ignores HTTP 404 and returns `None` whenever the response lacks a truthy `found`. A response identifying a missing index can therefore be mistaken for a missing conversation. [query-api/src/assistant/storage.py:L56](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/storage.py#L56) |
| Authentication | The whole Assistant router requires an admin JWT. Missing or invalid credentials return `401`; invalid authentication configuration returns `503`. [query-api/src/main.py:L119](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/main.py#L119), [query-api/src/auth.py:L39](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/auth.py#L39) |
| Generation errors | `post_message()` rethrows `StorageError` and maps other generation exceptions to `502`. Persistence happens after generation. [query-api/src/assistant/router.py:L85](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/router.py#L85) |
| Concurrency | The route reads history, generates a turn and performs an unconditional replacement. Neither read nor write carries a revision precondition. [query-api/src/assistant/router.py:L82](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/router.py#L82), [query-api/src/assistant/storage.py:L72](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/storage.py#L72) |
| Turn boundaries | `run_chat_turn()` returns all new messages for one turn, including user, assistant and possible tool messages. Undo cannot assume that a turn contains exactly two messages. [query-api/src/assistant/service.py:L87](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/assistant/service.py#L87) |
| Client cancellation | `handleStop()` aborts the browser request and restores the draft. It does not establish server rollback. [web/src/components/incident/AssistantPanel.tsx:L91](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/web/src/components/incident/AssistantPanel.tsx#L91) |

The verified call path is `AssistantPanel.handleSend()` → `useSendAssistantMessage()` → `sendAssistantMessage()` → `post_message()` → `ConversationRepository.get()` → `run_chat_turn()` → `ConversationRepository.save()` → OpenSearch. Generation may perform read-only Assistant tool calls before persistence.

Earlier read-only probes using the actual repository class with memory-only clients reproduced:

- Interleaved saves from history `H` produced `H + B`, losing A.
- An ignored missing-index response produced `None`.

These probes establish the inspected Python code paths; they are not real OpenSearch integration tests or executions of the future Undo implementation.

### Acceptance criteria — exactly five

| ID | Measurable acceptance criterion |
|---|---|
| **AC-01** | After a successful Send changes history `H` to `H + T`, Undo using its current revision returns `200` and restores message history deeply equal to `H`, including message order, timestamps, null values and tool-call fields. GET and API restart preserve the restoration. Undo is consumed once; a second Undo returns `409`. Undo of the first Send produces a persisted empty history. |
| **AC-02** | Send rejects missing, null, non-string, empty, whitespace-only and over-4000-character messages with `422`, without AI calls or writes. Meaningful messages of 1 and 4000 Unicode code points are accepted. Empty history remains valid for an absent conversation and first-Send Undo. |
| **AC-03** | Undo rejects missing, null, wrong-type and malformed revisions with `422`; a well-formed stale revision returns `409`. Rejected requests leave messages, recovery data and revision unchanged. |
| **AC-04** | Conversation read, write and mapping failures propagate as errors and return `503`, never `200` with empty/default data. A missing conversation index is a storage failure. Definite pre-write failures leave state unchanged. The swallowed-exception mutation must fail its designated test. |
| **AC-05** | For competing mutations based on the same persisted version, at most one succeeds. The other returns `409`; no committed conversation change is silently overwritten. Verify Send/Send, Undo/Undo and Send/Undo races, including concurrent first creation. |

### Non-functional constraints

- **Performance:** authenticated Undo API p95 ≤ 2.0 seconds with 60 concurrent tasks against real OpenSearch, for the benchmark workloads defined below. Live Azure OpenAI Send latency is excluded and reported separately.
- **Durability:** recovery survives API process restart; it is stored in OpenSearch, not browser memory or a process-local dictionary.
- **Compatibility:** legacy conversations remain readable and initially have no Undo opportunity. Preserve the current shared-admin authorization model.
- **Scope:** no new production dependency, service, database, multi-level history or redo mechanism.

### Most important invariant

**A conversation mutation may commit only against the exact version it was based on; the new message history and its recovery snapshot must be committed together.**

Supporting invariants:

- The recovery snapshot contains exactly one previous message array, never another snapshot.
- Legitimate empty history is distinguishable from unavailable or corrupt storage.
- Existing conversation `created_at` and all restored message fields remain unchanged.
- Successful Undo receives a new revision and `updated_at`; those values are not rolled back.
- Mutations affect only the requested cluster.
- Undo performs no Azure OpenAI or Assistant tool calls.

“Exact previous conversation” means deep JSON equality of the previous message history, with all message fields preserved. It does not mean restoring an old persistence revision or old conversation modification time. Undo of the first Send leaves an empty persisted conversation rather than deleting the document.

### Final API contract — proposed behavior, not implemented yet

All three endpoints retain admin JWT protection.

| Endpoint | Request | Successful response |
|---|---|---|
| `GET /assistant/clusters/{cluster_id}/conversation` | No body | `200`, conversation response below |
| `POST /assistant/clusters/{cluster_id}/conversation/messages` | `{"message": string}` | `200`, conversation response after conditional persistence |
| `POST /assistant/clusters/{cluster_id}/conversation/undo` | `{"expected_revision": string}` | `200`, restored conversation response |

Conversation response:

```json
{
  "cluster_id": "c1",
  "messages": [],
  "revision": "1:0",
  "undo_available": false
}
```

- `revision` is `null` only when no conversation document exists.
- A persisted empty conversation has a non-null revision.
- Public responses never expose the recovery snapshot.
- Existing message field names and meanings remain unchanged.
- Both POST request models reject unexpected fields.
- Send checks raw string length before any transformation and rejects `message.strip() == ""`. It preserves accepted API message text. The browser may retain its existing trimming behavior.
- Revision serialization is canonical `<primary_term>:<seq_no>`. Primary term is a positive integer; sequence number is nonnegative. Both are bounded by signed 64-bit maximum, `9223372036854775807`. Reject signs, whitespace, leading zeroes other than sequence number `0`, oversized components and noncanonical forms. Clients treat the token as opaque.

Error behavior:

| Status | Meaning |
|---|---|
| `401` | Missing, invalid or expired JWT; retain `WWW-Authenticate: Bearer` |
| `404` | Cluster not found; retain `{"detail":"cluster not found"}` |
| `422` | Invalid request fields or revision syntax; retain FastAPI validation error structure |
| `409` | `{"detail":"revision_conflict"}` for stale revision or conditional-write conflict |
| `409` | `{"detail":"nothing_to_undo"}` when the current revision has no recovery snapshot |
| `503` | Conversation persistence/configuration failure; use the existing storage-error envelope with a sanitized `detail` |
| `502` | Send generation failure; preserve existing behavior |

For an existing cluster with no conversation, GET returns `{"cluster_id":"c1","messages":[],"revision":null,"undo_available":false}`. Undo with a syntactically valid token has no matching document revision and returns `409` with `revision_conflict`. A legacy persisted document has a real revision but no snapshot; Undo with that current revision returns `nothing_to_undo`.

For Undo, check revision equality before checking snapshot availability. Consequently, retrying an already successful Undo with its old revision returns `revision_conflict`.

A write timeout can have an uncertain commit outcome. Return an error, refetch state and avoid automatic mutation retries. Do not claim that every timeout guarantees unchanged storage.

### State transitions

Let `H` be the previous message history and `T` all messages generated during one completed Send.

| Transition | Result |
|---|---|
| Successful Send | `H → H + T`; persist one snapshot containing `H` |
| Successful Undo | `H + T → H`; consume the snapshot and issue a new revision |
| First-Send Undo | Restore `[]` as a persisted conversation; Undo becomes unavailable |
| Send A, Send B, Undo B | Retain A; the snapshot from before A is not available |
| Subsequent successful Send | Replace the single snapshot with the history immediately before that Send |
| Rejected request | Do not mutate messages, snapshot or revision |

Repeated message text is a legitimate new Send, not an idempotency key. This feature does not recover history lost before it existed, undo an in-flight AI request or provide redo.

## 2. Review and corrections to the previous AI proposal

### AI-REV-01 — Missing document versus missing index

**Original AI statement:** the repository distinguishes missing conversations (`None`) from failed reads (`StorageError`).

**Evidence:** `ConversationRepository.get()` uses `ignore=[404]` and checks only `response.get("found")`. A memory-only probe returned `None` for a response containing `index_not_found_exception`. The existing user repository already distinguishes these cases: [query-api/src/users.py:L51](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/src/users.py#L51).

**Risk:** a storage/index problem can appear as a successful empty conversation. Send may then proceed from a false empty baseline.

**Proposed correction:** remove blanket 404 suppression. Return `None` only for a genuine document-not-found outcome; classify missing index, malformed responses and connection errors as `StorageError`.

**Consequences:** add separate missing-document and missing-index tests through the actual conversation repository. The API failure test must assert that neither generation nor replacement occurred.

### AI-REV-02 — Revision contract was insufficiently specified

**Original AI proposal:** use an opaque revision string of at most 128 characters and reject stale revisions.

**Evidence:** the current `get()` discards version metadata; `save()` ignores the indexing response and wraps every client exception as `StorageError`. No current method can provide the proposed revision or distinguish conflict from unavailability.

**Risk:** an implementer could use timestamps as revisions, reject valid sequence number zero, or convert OpenSearch conflicts to `503`.

**Proposed correction:** use the explicit sequence-number/primary-term token defined above. Carry that metadata internally, require conditional replacement, use create-only semantics for a missing document, and catch OpenSearch conflict errors before the generic exception handler.

**Consequences:** test token `1:0`, numeric boundaries, stale tokens, returned metadata and conflict-to-409 mapping. Never permit an unconditional-save fallback.

### AI-REV-03 — Reusing tests requires replacing their persistence model

**Original AI proposal:** extend the existing Assistant API and repository tests.

**Evidence:** the API fake replaces a dictionary document without revisions. The repository fake accepts and ignores extra indexing arguments and stores mutable object references. [query-api/tests/test_assistant.py:L45](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/tests/test_assistant.py#L45), [query-api/tests/test_assistant_storage.py:L27](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/query-api/tests/test_assistant_storage.py#L27).

**Risk:** unchanged fakes cannot detect omitted concurrency arguments or snapshot aliasing.

**Proposed correction:** retain the test organization but make persistence fakes deep-copy documents, return metadata, enforce conditional writes and model creation conflicts. Use real OpenSearch tests as the authority for concurrency behavior.

**Consequences:** fake-based tests prove routing and request construction; real integration tests prove persistence semantics. This refines test reuse rather than asserting that the earlier plan omitted real integration testing.

## 3. Risk-based test plan — planned verification

Priorities: **P0** protects data or failure semantics; **P1** verifies compatibility and user workflow. None of the tests below has been implemented or executed as part of this planning-document step.

| Test ID | AC / risk | Level | Precondition and input | Expected outcome | Priority |
|---|---|---|---|---|---|
| T-01 | AC-01; response contract | Integration/API | Existing cluster, absent conversation; authenticated GET | `200`, empty messages, null revision, Undo false; no write | P0 |
| T-02 | AC-01; exact restoration | Integration/API | Seed Unicode history H, null-content assistant tool call and matching tool response; Send T, then Undo | Restored messages deeply equal H; GET agrees | P0 |
| T-03 | AC-01; one-level boundary | Integration/API | First completed Send from no conversation; Undo | Persisted empty messages, new revision, Undo false | P0 |
| T-04 | AC-01/03; repeat Undo | Integration/API | Successful Undo; retry old revision, then request current revision | Old token: `revision_conflict`; current token: `nothing_to_undo`; both `409` | P0 |
| T-05 | AC-01; one-level semantics | Integration/API | Send A, Send B, Undo B | A remains; another Undo cannot remove A | P0 |
| T-06 | AC-02; invalid partition | Integration/API | Message missing, null, number, boolean, array, object, `""`, spaces, tabs/newlines | `422`; no generation or write | P0 |
| T-07 | AC-02; length boundaries | Integration/API | Nonblank strings of 1, 3999, 4000 and 4001 code points, including emoji | First three accepted; 4001 rejected; accepted text preserved | P0 |
| T-08 | AC-03; revision validation | Unit + API | Missing/null/numeric/empty token; malformed separators, signs, leading zeroes or overflow | `422`; no mutation | P0 |
| T-09 | AC-03; version boundaries | Unit + repository | `1:0`, maximum supported components and one-above-maximum | Valid boundary tokens parse; overflow rejects; zero sequence is valid | P0 |
| T-10 | AC-03/05; stale client | Integration/API | Read revision R, commit newer Send, Undo using R | `409`; newer state and snapshot unchanged | P0 |
| T-11 | AC-04; read failure | Integration/API | Existing H; actual repository client raises connection error on read | `503`; no AI call or write; H preserved | P0 |
| T-12 | AC-04; missing index | Integration/API | Conversation index unavailable; request GET and Send | `503`, never empty `200`; no replacement | P0 |
| T-13 | AC-04; write failure | Repository + API | Eligible snapshot; inject definite pre-commit write rejection | `503`; messages, snapshot and revision unchanged | P0 |
| T-14 | AC-05; Send race | Integration/API | Barrier forces two Sends to read the same version; repeat from absent document | One `200`, one `409`; winning turn retained | P0 |
| T-15 | AC-05; Undo race | Integration/API | Two Undos use the same eligible revision | One `200`, one `409`; restoration happens once | P0 |
| T-16 | AC-05; mixed race | Integration/API | Send and Undo share the same starting version; test each winner ordering | One succeeds; loser conflicts; final state matches winner | P0 |
| T-17 | AC-04; mutation | Unit + API | Replace repository read exception propagation with `return None`; execute T-11 | Test fails on missing exception/wrong status or side effects; mutant killed | P0 |
| T-18 | AC-01/04; compatibility | Integration | Existing strict index and legacy document without snapshot; run mapping setup twice | Idempotent mapping update; legacy data preserved; Undo initially unavailable | P1 |
| T-19 | Authentication | Integration/API | Missing, invalid, expired JWT; valid-shaped requests | `401`; no conversation access or AI call | P0 |
| T-20 | AC-01; durability/UI | E2E | Real API/OpenSearch; test-only deterministic generation | Send → Undo → reload and API restart preserves H; no browser API interception | P1 |
| T-21 | AC-03/04; frontend errors | Unit/component | Undo returns `409`, `503` or network error | No optimistic removal; show error and reconcile with GET | P1 |
| T-22 | AC-01/04; corrupt snapshot | Repository + API | Current document contains invalid recovery metadata | `503`; no write or empty-success default | P0 |

**Contract testing:** T-01–T-13 validate provider response schemas, statuses and state effects. Frontend tests verify the same fields and error meanings. Repository contracts verify actual OpenSearch request preconditions and responses. Use JSON Schema with explicit date-time format checking; an HTTP status assertion alone is insufficient.

**Boundary-value analysis:** choose message lengths 0, 1, 3999, 4000 and 4001; absent versus empty histories; primary term one; sequence number zero; maximum numeric components and overflow.

**Equivalence partitioning:** separate meaningful strings, whitespace-only strings, incorrect JSON types, genuine missing documents, unavailable indexes, valid/current revisions, valid/stale revisions and malformed revisions. Repeated message text is valid input and is not a deduplication key.

Use fixed timestamps and deterministic generation. Use deep copies and cluster-specific IDs so test isolation cannot conceal shared-state bugs. Test absence, empty history and first-Send recovery separately rather than treating all empty-looking values as equivalent.

### Deliberate swallowed-exception mutation

The planned mutation changes the conversation repository read exception handler from raising `StorageError` to swallowing the exception and returning `None`.

The designated test seeds H, injects a client read exception and sends a valid API message. The unmutated implementation must return `503`, perform no generation or write, and preserve H. A repository-level companion assertion must require `StorageError`.

The mutant must fail those assertions. In a version-protected implementation, an erroneous creation attempt may instead conflict; that still violates the required read-failure contract and must not be counted as a surviving mutation. Record the original result, the exact temporary mutation, the failing assertion, source restoration and the final rerun. Do not leave the mutant in the final diff.

## 4. Minimal implementation and expected files — future work

### Backend design

- Introduce an internal conversation state containing the document, sequence number and primary term. Public responses project only messages, revision and Undo availability.
- Change repository `get()` to return that state or genuine absence. Change `save()` to require the previously read state, including explicit absence; remove unconditional replacement capability from the Assistant path.
- On Send, write `H + T` and `undo: {"messages": H}` together in one conditional document replacement.
- On first creation, use create-only persistence. Concurrent creation becomes `409`.
- On Undo, read the latest state, check the supplied revision, restore its snapshot, set `undo` to null and conditionally replace the document.
- Snapshot only the previous messages, without nesting recovery metadata. Preserve existing conversation creation time; advance modification time.
- Add optional recovery metadata to the stored schema and an explicitly disabled-indexing object mapping. Update existing mappings additively and idempotently; never recreate the index.
- Use sanitized `StorageError` messages. Preserve the existing application error handler.
- Deploy the backend as one version; mixed old/new writers are unsupported because an old writer can remove recovery metadata.

Use OpenSearch conditional writes through `if_seq_no` and `if_primary_term`; a genuine absent document must use create-only semantics. These facilities already exist in the repository's OpenSearch 2.17 backend and do not require a new production dependency. [OpenSearch 2.17 Index document API](https://docs.opensearch.org/2.17/api-reference/document-apis/index-document/)

### Frontend design

- Extend the conversation type and add an Undo POST client using the existing authenticated transport.
- Add an Undo mutation using the current cached revision.
- Display “Hoàn tác lượt gửi”; disable Send and Undo while either mutation is pending.
- Update the cache only after confirmed success. On conflict or uncertain outcome, refetch; never retry a mutation automatically.
- Keep all existing message rendering, including tool messages. Browser Stop remains cancellation, not Undo.

### Exact expected files

Only the first row is authorized in the current planning-document step. All other rows describe future implementation, subject to a separate instruction.

| Repository-relative file | Purpose |
|---|---|
| `docs/assignments/VT-013/plan.md` | This specification and review record; the only immediate deliverable |
| `query-api/src/assistant/router.py` | Validation, response contract, Undo endpoint and conflict mapping |
| `query-api/src/assistant/storage.py` | Version-aware state, conditional writes, snapshot restoration and mapping update |
| `docs/architect/contracts/assistant-conversation-schema.json` | Optional recovery metadata compatible with legacy documents |
| `docs/architect/contracts/api-contract.md` | Public contract additions and error behavior |
| `query-api/tests/test_assistant.py` | Failing API contracts and updated API fakes |
| `query-api/tests/test_assistant_storage.py` | Failure, version, snapshot and request-construction tests |
| `query-api/tests/test_assistant_undo_integration.py` | Real OpenSearch, restart and concurrency verification |
| `query-api/tests/vt013_test_server.py` | Loopback-only test server using real OpenSearch and deterministic generation |
| `web/src/lib/api.ts` | Conversation types and Undo request |
| `web/src/lib/queries.ts` | Undo mutation and cache reconciliation |
| `web/src/components/incident/AssistantPanel.tsx` | Minimal Undo action and errors |
| `web/src/lib/api.test.ts` | Consumer contract tests |
| `web/src/components/incident/AssistantPanel.test.tsx` | Pending, success, conflict and failure behavior |
| `web/playwright.vt013.config.ts` | Isolated frontend/API test processes |
| `web/vt013-e2e/assistant-undo.spec.ts` | Critical real-persistence browser scenario, outside existing default test directories |
| `load-tests/vt013_undo.py` | Dedicated 60-task benchmark using existing HTTPX and standard-library threading |

No production changes are expected in Assistant generation, authentication, clustering, ingestion, Caddy or generic application configuration.

## 5. Test-first sequence, verification and AI evidence

### Implementation sequence — not executed during this step

1. **Failing API contract tests:** add request/response, first Undo, one-level, revision and storage-error cases. Record expected failures against the unchanged implementation.
2. **Failing repository tests:** add metadata, snapshot copying, conditional replacement, create-only creation, mapping compatibility and missing-index cases.
3. **Minimal backend patch:** implement the repository behavior, endpoint and schema updates. Keep generation unchanged.
4. **Verification and diff review:** run focused tests, real OpenSearch integration and existing Query API regression tests. Check for unconditional writes, swallowed storage errors, nested snapshots and unrelated edits.
5. **Minimal frontend action:** implement typed client, mutation and button; run consumer/component tests and the isolated E2E scenario.
6. **Mutation experiment:** temporarily change the repository read exception handler to return `None`; run T-11/T-17, capture the failing assertion, restore the source and rerun successfully. Do not commit the mutant.
7. **Coverage and flaky-test review:** collect Python statement coverage using standard-library `trace`, with reports outside tracked source. Review every changed executable line and require coverage of all P0 outcomes. Repeat concurrency cases 100 times and the E2E scenario 10 times without retries concealing failures.
8. **Performance verification:** run the benchmark below and retain measured evidence.

Use the repository's existing Python development requirements and frontend lockfile when the later implementation environment is prepared. Do not install dependencies during this planning step. Run lint, TypeScript/build checks and Vitest through existing npm scripts. Standard-library trace reports statement coverage only; do not label it branch coverage.

### Performance protocol — planned verification

- Use a disposable OpenSearch 2.17.1 instance and the loopback test API. Production persistence and authentication remain real; only generation is replaced inside the test harness.
- Use unique, explicitly test-prefixed indexes and ephemeral admin credentials. The harness must refuse non-test index names.
- Test prior histories of **0, 2 and 100 messages**, with 1 KiB content per non-null message. Include representative Unicode/tool fields; message-size boundary tests remain separate.
- Prepare 60 independent eligible conversations outside the timed interval.
- Use 60 worker threads and a barrier to release their Undo requests together.
- Run five warm-up rounds, then 50 measured rounds per history class: **3,000 measured Undo requests per class**.
- Re-arm Undo between rounds using deterministic Send, outside measured Undo latency.
- Measure the complete HTTP request/response and JSON decoding interval. Do not run statement tracing during the benchmark.
- Compute p95 by nearest rank from raw samples. Each class must meet p95 ≤ 2000 ms with zero unexpected failures, no timeouts and correct final histories.
- Report contention conflicts separately; never mix fast `409` responses into successful Undo latency.
- Record CPU/RAM, process count, OpenSearch settings, payload sizes, throughput, p95/p99/max, errors and raw samples. Larger histories are outside this initial performance claim.

Existing historical evidence covers 20 users before JWT, so it is not evidence that VT-013 meets this target. [load-tests/README.md:L126](https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/a2e0c070d694054001767979fe3f247e7ebff6be/load-tests/README.md#L126)

### Required future engineering evidence

Keep red/green test output, baseline and final SHAs, contract results, real integration results, E2E result, the mutation diff and failing assertion, restored-source result, statement coverage, repeated-run results and performance samples. Store reviewable evidence under the assignment directory when later authorized. Record commands, environment and failures accurately; skipped checks are not passes.

### Actual executed evidence and limitations

| Activity | Actual observation | Limit of the evidence |
|---|---|---|
| Branch and HEAD inspection | The planning step starts on `feat/vt013-undo-manhpd` at `a2e0c070d694054001767979fe3f247e7ebff6be` | This identifies the local baseline, not the current live GitHub branch tips |
| Working-tree inspection before creation | No tracked or staged changes; pre-existing untracked entries were `docs/chatgpt-context-vi.md`, `graphify-out/`, `upgrade_assignment.md` and `upgrade_assignment_new.md` | These unrelated entries are not part of this document or the assignment diff |
| Source inspection | Verified the contracts and functions linked in Section 1; re-read core route, repository, error-handler and fake-client code before creating this document | Static inspection is not an execution of the proposed feature |
| Earlier Graphify review | All 172 indexed files matched recorded hashes; the graph has 1,458 nodes and 2,885 edges | Recorded extraction warnings and two merged self-loops remain; broad query output was truncated and focused symbol inspection was also used |
| Earlier memory-only repository probes | Actual Python repository logic lost A in an interleaved `H + A` / `H + B` replacement; an ignored missing-index response became `None` | Fake clients were used; no real OpenSearch transaction or HTTP API was tested |
| Earlier tooling inspection | The inspected Python interpreter lacked FastAPI, Pydantic, the OpenSearch client and Locust | No dependencies were installed; another interpreter or deployment may differ |

No pytest suite, real OpenSearch integration test, browser E2E, swallowed-exception mutation, coverage measurement or performance experiment has been executed for the proposed Undo feature. All T-01–T-22 outcomes and performance thresholds remain expected results, not passed results.

The documentation-only completion check is `git diff --check` and `git diff`. A newly created, unstaged file does not appear in ordinary `git diff`; inspect it additionally with `git diff --no-index` against the null device, including `--check` and `--stat`. A no-index diff exit status of 1 means differences were found, not that verification failed. Report actual command results separately after writing, without staging the document just to expose its diff.

### AI usage record

- **Human request:** finalize VT-013 specification and review the earlier AI plan before production changes; subsequently create only the approved planning document.
- **AI contribution:** repository inspection, Graphify navigation, source-linked contract analysis, risk identification and this proposed test/implementation plan.
- **Human decisions confirmed:** use the current assignment branch baseline; allow all authenticated admins to Undo the current revision; apply the two-second target to Undo API.
- **Corrections recorded:** missing-index classification, explicit revision semantics and required changes to persistence fakes.
- **Graphify accounting:** token accounting is unavailable; zero-valued fields in existing accounting files are placeholders, not a claim of zero token use.
- **Executed versus planned:** actual analysis activities are listed above; implementation and verification experiments remain future work.
- **Authorization boundary:** creating this document does not authorize editing production code or tests, applying a mutation, installing dependencies, committing or pushing.

### Assumptions, compatibility and review boundaries

- The human-selected action is Undo the latest completed Send. Normal Send is logically append-only but implemented as document replacement; this is the selected data-loss-risk action, not an existing Delete feature.
- Conversations remain shared per cluster. All authenticated admins may Undo the current revision; sender-only authorization is outside the approved specification.
- Undo is one level, with no redo, automatic expiry or recovery of already lost historical data.
- The performance target applies to Undo and the stated benchmark sizes. It does not establish a guarantee for unbounded histories or live Azure OpenAI Send latency.
- Deployed legacy document contents, actual mapping compatibility and runtime performance still require real integration evidence. Mixed old/new writers must not be used to validate the invariants.
- Local `main` and cached `origin/main` contain newer changes, including the shared API client. Recheck that comparison before any later PR and preserve unrelated work. Do not update the assignment branch during this documentation step.
- Shared contract files require team coordination under repository conventions before future implementation changes. This step records proposed contract edits without making them.
- After this document is created, stop for review. Do not create a commit, push, open a PR or implement the future sequence.
