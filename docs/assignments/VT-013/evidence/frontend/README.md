# VT-013 frontend Undo — executed verification

## Outcome and scope

Implemented **Hoàn tác lượt gửi** for the latest completed Assistant Send.
The frontend preserves the existing message/tool rendering and uses the backend's
complete response as its history. There is no optimistic deletion, locally guessed
turn boundary, generated revision or automatic Undo retry.

Starting branch: `feat/vt013-undo-manhpd`; starting and final HEAD:
`17ae52feae4e3f799f2249478ac2434ab869ceba`. That checkpoint actually contains the
backend and prior integration evidence. The tracked worktree was initially clean;
previously excluded local diagnostics and unrelated untracked files already existed.
No backend production file, published contract, dependency declaration, lockfile,
existing test, other service, commit, push, merge or PR is changed by this step.

Production changes are limited to:

- `web/src/lib/api.ts`: required typed `revision`/`undo_available`, strict wire-token
  validation, and an Undo request through the existing authenticated client.
- `web/src/lib/queries.ts`: Undo mutation, explicit `retry:false` for both Assistant
  mutations, cancellation of stale GETs, exact server response cache replacement,
  GET reconciliation after non-401 failure/Stop, and a session check before cache writes.
- `web/src/components/incident/AssistantPanel.tsx`: accessible Undo action, shared
  pending-state disabling, synchronous duplicate-click guard, error/reload states,
  preserved draft, explicit cancellation status and cluster-scoped component lifetime.

New tests are `web/src/lib/assistant-undo.test.ts` and
`web/src/components/incident/AssistantPanel.test.tsx`. Real browser verification
adds `web/playwright.vt013.config.ts` and
`web/e2e/integration/assistant-undo.pw.ts`. Test/evidence runners are local to this
directory. The backend test server/helper is reused without modifying it.

## Contracts explained before implementation

Existing Send: `AssistantPanel.handleSend` trims the draft, uses an AbortController
and calls `useSendAssistantMessage`, then `sendAssistantMessage` and `queryJson`.
Successful responses replace `['assistant-conversation', clusterId]` in React Query.
The original hooks neither cancelled in-flight GETs nor reconciled failed mutations.
Stop aborted only the browser request and restored the draft, with no server rollback.

GET/Send/Undo responses contain `cluster_id`, complete `messages`, `revision` and
`undo_available`. Revision is null only for an absent document. A persisted empty
history has a real revision. Legacy documents return a real revision with Undo false.
The browser accepts only canonical ASCII `primary_term:seq_no` tokens with term ≥ 1,
sequence ≥ 0, both ≤ signed-64-bit maximum; it forwards the original string unchanged.
It does not order tokens, manufacture metadata or roll a revision backward.

Undo is `POST /assistant/clusters/{encoded-id}/conversation/undo` with exactly
`{"expected_revision":"<current server token>"}`. It uses the current Bearer token,
JSON content type, `credentials:omit`, `redirect:error` and `cache:no-store` through
the unchanged shared client. Success is HTTP 200 with the complete restored history,
a new revision and `undo_available:false`. The snapshot is not exposed to the UI.

HTTP 409 is a conflict/no-Undo result and requires GET reconciliation, with no local
deletion. HTTP 503 or network failure can leave the commit outcome uncertain: retain
the current cache until GET confirms server state; do not retry the mutation.
401 continues the existing session-expiry handling. Invalid request/token values
remain 422; the client additionally rejects malformed Undo tokens before fetching.

Pending Send or Undo disables both mutations and the input. Undo remains pending
through its failure reconciliation. If reconciliation fails, cached messages remain
visible, stale Undo is disabled and a manual **Tải lại hội thoại** GET is available.
Stop remains cancellation and never invokes Undo; the UI states that the server may
still process the Send. GET reconciliation is immediate when mounted and is otherwise
retried by normal fresh loading when the panel is opened again. A later server commit
after a cancelled Send cannot be ruled out by a single earlier GET.

The invariant is that only the server determines history and revisions. Backend CAS
continues to arbitrate competing writes; frontend disabled states are not a lock for
other administrators or tabs. Old GETs are cancelled before mutation and before a
confirmed response enters cache. Both success callbacks verify the current session
again after that asynchronous cancellation, preventing post-logout cache repopulation.

## Actual results

- Initial RED: **37 failed**, exit **1**, zero collection/import errors. Production
  hashes before/after are identical. Missing Undo export/action caused the Undo
  failures. Stop failed the enabled-input assertion while its aborted Send remained
  pending under the test's global mutation retry policy; subsequent GET assertions
  were not reached in RED. These were assertion failures, not environment blockers.
- Follow-up session-race RED: **1 failed**, exit **1**; 22 other cases were filtered
  by `-t F-10` and are not counted as passes. It reproduced a cleared cache being
  repopulated during a confirmed mutation callback after logout.
- Final targeted suite: **38/38 PASS**, exit **0** (15 API, 23 component/cache cases).
- Full frontend Vitest suite: **140/140 PASS**, exit **0**: 38 new cases plus 102
  unchanged existing cases. The targeted rerun is not 38 extra unique cases.
- Application TypeScript `tsc -b`: **PASS**, exit **0**.
- Standalone Playwright config/spec TypeScript check: **PASS**, exit **0**.
- Lint: **PASS**, exit **0**, with nine existing warnings in unrelated source files;
  none in the changed frontend production files or new tests/config.
- Vite production build: **PASS**, exit **0**, after successful application typecheck.
  Together these are the same two checks run by `npm run build`.
- Real Chrome → Query API → OpenSearch E2E: **1/1 PASS**, exit **0**, without test retries.
- Final `git diff --check`: **PASS**. Source hashes and final scope checks are in
  `review-results.json`; no files are staged and HEAD is unchanged.

See `test-results.md`, the RED/GREEN logs and JUnit, `green-results.json`,
`extra-checks.json` and `e2e-results.json` for commands, versions, exit codes and
per-case evidence. All claimed results above were executed.

## Real browser persistence evidence

`run_e2e.py` creates a labelled, uniquely named OpenSearch **2.17.1** container,
checks its exact cluster identity and loopback endpoint before writing, and uses
fresh `vt013-frontend-<run-id>-*` indexes. Data is in disposable tmpfs, with no shared
project mounts. No existing index is deleted/reset. OpenSearch security is disabled
only inside that isolated node; actual application admin authentication is preserved.

The existing APIProcess harness runs the actual application/repository and stores an
actual Argon2 admin. The browser logs in through `/auth/login`; there are no auth
overrides, intercepted API responses or fake persistence. Only AI generation is
deterministic, in the existing test-only server entry point. A separate owned Vite
process serves the frontend on a random loopback port. No existing service is reused.

The scenario starts with a valid legacy conversation containing Unicode, null content
and tool messages. Browser Send advances revision `1:0 → 1:1`; Undo restores the
complete original history at `1:2`; browser reload fetches the same history/revision.
The runner independently reads OpenSearch `_source` and sequence metadata and asserts
exact message equality, unchanged creation time, consumed snapshot and matching GET
revision. `e2e-before.persisted.json`, `e2e-after.persisted.json` and
`e2e-browser-proof.json` preserve that evidence. Both API/Vite processes and the exact
owned OpenSearch container were stopped; `owned_container_removed:true` is recorded.
Browser traces/screenshots/video and runtime passwords/JWTs are not saved.

## Diagnosed failures and corrections

`initial-green/` retains the first complete verification and source snapshots:
37 targeted cases passed, but one of 139 total cases failed because a local Jaeger
URL contradicted an existing regression's explicit unconfigured-environment premise.
The runner now sets `VITE_JAEGER_URL=""` in the Vitest process; no `.env` file or test
expectation is edited. Typecheck also rejected an unsupported `exact` option on RTL's
`getByRole`; it was removed, preserving its default exact string-name matching.
New ref-read lint warnings were resolved with state for the Stop button.

The session-race test was then written and executed before its correction. Its
failure showed why the existing API session check alone is insufficient across a new
asynchronous cache callback. Capturing the initial session token and checking it
immediately before cache replacement fixed that race. No assertion was weakened.

`initial-e2e/e2e-typecheck-initial.log` records a command-configuration failure, TS5112: TypeScript
6 requires `--ignoreConfig` when source files and standalone options are specified
while tsconfig.json exists. The corrected standalone command passed; application
`tsc -b` had already passed. This was not a production type error or an E2E failure.

Final review also isolated the browser scenario as `.pw.ts`, selected only by the
VT-013 config. Otherwise the existing auth integration config would collect a new
`.spec.ts` requiring VT-013-only environment. Discovery checks now prove that normal
and auth suites exclude it, while VT-013 selects exactly one case. The initial
successful browser run is archived in `initial-e2e/`; the scenario was rerun after
this configuration correction. It is still one unique E2E scenario, not two.

Build output retains the bundle-size warning for chunks above 500 kB. Playwright
retains its harmless FORCE_COLOR/NO_COLOR environment warning. These are not hidden
or reported as zero-warning checks.

## Reproduction

From the repository root, with existing web dependencies installed:

```powershell
python -u -B docs/assignments/VT-013/evidence/frontend/run_frontend.py green
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B docs/assignments/VT-013/evidence/frontend/run_e2e.py
```

The first runner executes the exact node/Vitest, tsc, oxlint and Vite commands stored
in its log headers and JSON. The second requires the existing backend development
dependencies, Docker Desktop, cached pinned image and installed Chrome; it installs
nothing. RED commands are preserved in `red-results.json`; reproducing RED requires
the recorded pre-change frontend source at the checkpoint, not running final code
and expecting failure. Copy/archive evidence before rerunning these overwrite-by-name
runners. The initial and final executions here are preserved separately.

## Limitations and stop point

The E2E uses a Vite development server, Chrome and one disposable OpenSearch node;
production bundle build is verified separately. It is not cross-browser, exhaustive
accessibility, TLS/failover, live Azure generation or a sustained concurrency test.
Existing auth/dashboard browser suites were discovery-checked only, not executed
against shared project data. The earlier backend suites were not rerun in this phase;
their production/test sources remain unchanged and their evidence is preserved.
Keyboard activation, accessible name, native disabled states and error/status roles
are covered by component tests. The 60-task/p95 performance and swallowed-exception
mutation experiments have not been run. No frontend commit/push/merge/PR was made.

Graphify navigation used the existing stale baseline index only as a map and every
conclusion was checked against source. Its CLI incidentally updated the pre-existing
untracked `graphify-out/cache/last_query_stamp` timestamp; this is recorded explicitly
in integrity evidence and is not part of the frontend code diff. The graph/index and
all backend files and other pre-existing files remain unchanged. Graph token accounting
is unavailable and the broad query was budget-truncated; no architectural claim rests
on its omitted results. Stop here for human review.
