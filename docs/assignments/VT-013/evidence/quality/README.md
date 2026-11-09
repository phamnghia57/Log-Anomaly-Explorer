# VT-013 quality review

Scope: verification only, branch `feat/vt013-undo-manhpd`, HEAD
`bc735253920db6bc51d19f12b0fb3d92f210a8c2`. No production code, existing tests,
assertions, approved contracts or dependency/lock files were changed. No retry
was added to a test. No performance benchmark, commit, push, merge or PR was run.

## Coverage and its limits

Python: the 90 existing Assistant API/repository/backend cases, real router and
repository over the OpenSearch transport fake and deterministic AI. `trace.Trace`
instruments the main thread **and new worker threads**, including FastAPI's sync
handlers. Reports: `python-coverage.json`, `storage.cover.txt`, `router.cover.txt`,
`python-coverage.log` and JUnit. Tests: 90 PASS, exit 0 in the corrected run.

- `query-api/src/assistant/storage.py`: **130/141 lines, 92.20%**.
- `query-api/src/assistant/router.py`: **90/99 lines, 90.91%**.
- Python branch coverage: **NOT MEASURED**. Stdlib trace cannot measure branches.
  These are compile-position/statement-line approximations, not coverage.py results.
  CPython 3.14 artificial None/zero line positions were excluded. Some multiline
  signature positions (storage lines 131/156) remain counted as unhit even though
  their functions executed; do not interpret every MISS as an executable gap.

Frontend: all **140 Vitest cases PASS**, exit 0, using the project's existing Vitest
5.0.3 and matched V8 provider 5.0.3. Source-mapped V8/Istanbul reports are under
`frontend-coverage/` (JSON, LCOV and HTML). Only the three requested modules are
included in the coverage denominator, while all existing frontend cases run.

- `web/src/lib/api.ts`: **51/51 lines, 100%**; **52/54 branches, 96.29%**.
- `web/src/lib/queries.ts`: **32/36 lines, 88.88%**; **13/17 branches, 76.47%**.
- `AssistantPanel.tsx`: **58/60 lines, 96.66%**; **65/73 branches, 89.04%**.
- Aggregate of those three files: **141/147 lines, 95.91%**, **130/144 branches,
  90.27%**, as printed by the provider (percent display is truncated).

`frontend-coverage-summary.json` lists every uncovered mapped statement/branch.
Line/branch metrics are tool-specific and not comparable to Python's trace
denominator. They measure these mocked-HTTP unit/component suites, not browser or
real-server execution. The real E2E runs are separate persistence evidence and are
not added to these coverage percentages. High percentages alone do not establish
AC completeness or correctness. Node 25.8.2 is outside Vitest's declared supported
engine ranges; npm's warning is retained here as a portability limit. Supported
Node LTS verification remains advisable despite the successful measured run.

## Important uncovered paths

Storage: cluster-identity mismatch (70), non-OpenSearch construction (84), unexpected
new-index creation errors (99), unacknowledged new index (103), non-exception
missing-document response (118), malformed Get response (120), pre-write schema
rejection (135–136), and client close (182). The last and constructor paths have
lower feature risk; identity/malformed/schema/creation errors deserve negative
contract cases. Actual missing-document/missing-index exception envelopes are
covered historically by real integration I-07, separately from this fake suite.

Router: unavailable cluster/conversation repositories (61–63,71), propagated
generation/tool StorageError (120–121), and ordinary generation failure/502
(122–124). They are meaningful AC-04/error-regression gaps in this measured suite.

Frontend: ordinary Send failure draft restoration (AssistantPanel 88–90 and
187–195); unknown/missing tool-label fallbacks (24); early-return guard path (116);
API default-base-URL and empty-error-body fallbacks (13–14,140); non-Assistant
query callbacks (27–39); Send's session-change cache rejection (queries 77) and
Send/Undo 401 mutation early returns (82,110). Undo's logout/cache-repopulation
race **is** covered by F-10; it is not evidence for all analogous Send branches.
Shared authenticated-client tests help but do not execute every hook-specific path.

The approved plan asks for coverage of every P0 outcome. That gate cannot be
declared fully satisfied with these unhit error paths. Proposed next work for human
review: add focused configuration/malformed-storage/schema and generation-failure
contracts, ordinary Send error/draft restoration, Send logout race and Undo 401
cache tests. No tests or assertions are modified in this verification phase.

## Risk matrix

`risk-matrix.json` maps **each AC-01 through AC-05** to test IDs, exact files,
test level/backing, executed evidence and residual risks. Highlights:

- AC-01: T-02/03/04/05/18 and F-03/07 check exact history, tool/null/Unicode fields,
  persisted empty history and one-level consumption. Current browser repetitions
  confirm actual nonempty restoration/reload; historical real I-03 covers first Undo.
- AC-02: T-06/07 and F-01 cover blank/type/Unicode-length and revision boundaries.
- AC-03: T-04/08/09/10 and F-01/04 cover invalid/stale tokens and conflict GET
  reconciliation. No primary-term failover is induced here.
- AC-04: T-11/12/13/18/22 and F-05 cover propagation, failures and uncertain outcomes.
  Historical M-01 was killed by four assertions; historical real I-07/10/11 cover
  actual SDK 404, refused connection and write rejection. They are not rerun here.
- AC-05: T-14/15/16 and F-06/09/10 check CAS/create-only contention, duplicate UI
  actions, stale GETs and logout cache races. Historical real CAS integration is
  distinct from this phase's 100-repeat fake-backed race runs.

Historical evidence is preserved under red/green/integration/frontend/mutation;
PASS there is labelled historical in the matrix. Current runs are not relabelled
as real persistence tests merely because they use the production repository.

## Scheduling, shared state and test order

`races-100.junit.xml`: **400/400 PASS**, exit 0. Each of four variants ran 100 times:
existing-document Send/Send, first-create Send/Send, Undo/Undo and Undo/Send.
The original deterministic barriers and bounded futures/joins were reused. No
arbitrary sleeps, status expectation changes or test retries were introduced.
Different winners are valid: tests require one 200/one 409, correct commit count
where asserted, and final persisted messages matching the winning response.
Winner frequency itself is not recorded; no claim of a fixed scheduling order is made.

`repeat_plugin.py` creates separate collected item copies with unique node IDs,
fresh fixture request state and teardown for each repetition; it does not change
test bodies/parameters/oracles. JUnit proves all 100 executions of every variant.
This demonstrates fake-backed transport/API stability, not 100 real OpenSearch races.

Backend reversed file order: **90/90 PASS**; focused contracts separately:
**14/14 PASS**; repository separately: **6/6 PASS**. The coverage run executes the
normal combined 90-case order. Frontend shuffled with seeds 13013 and 13014:
**140/140 PASS each**. Component fixtures use fresh QueryClients, cleanup, cleared
auth state/mocks; these assertions and varied ordering found no state leak in the
executed scope. This is finite sampling, not proof of all orders or zero flakiness.

## Network/time and real browser repetitions

See `final-summary.json` for the final counted browser runs. The target is ten
actual executions of the unchanged `assistant-undo.pw.ts`, not ten successful
preflight probes. Each uses a fresh labelled OpenSearch 2.17.1 container and index
prefix, actual admin login/API/persistence, separate owned Vite/API processes and
deterministic test-only generation. Exact before/after raw documents and browser
proof are retained per run; owned container cleanup is checked each time.

The quality-only Playwright config routes JUnit/output into this directory, keeping
all historical frontend evidence untouched. It sets retries=0 and disables trace,
video and screenshots to avoid recording credentials. API/OS version and identity
must match before writes. Readiness polling has explicit 120/45/30-second budgets;
only startup polling sleeps. Those sleeps are not used for race synchronization.
Test timeout is 45 seconds, HTTP readiness calls 2 seconds and requests bounded.
Automatic **test** retries are zero. Existing application GET retry policy and SDK
transport retries remain unchanged; their internal attempts were not individually
instrumented. Ten scenario passes do not prove zero underlying wire-level retries.

Seed messages use fixed ISO UTC timestamps; JWT expiry uses current wall time plus
one hour. UUIDs and ephemeral credentials isolate resources and are not expected
business values. The browser navigates directly to its cluster ID, avoiding the
dashboard's wall-clock retention filter. The fixed cluster timestamps can age out
of the dashboard: dashboard discovery across dates is not verified by this scenario.
Clock jumps, suspend/resume and timezone changes are untested; there is no fake-clock
control in the live browser. No live Azure or other external AI request is made.

## Setup/reporting failures retained, not hidden as retries

- The first Python run passed all 90 tests, then its reporting helper failed sorting
  a None line position. `.initial` logs/JUnit/source are retained. Filtering artificial
  positions corrected only the evidence reporter; the traced 90-case rerun passed.
- A temporary standalone Vitest CLI lacked jsdom (no tests ran). A second standalone
  attempt had mismatched matcher runtime identity (51 false failures such as invalid
  Chai `toBeInTheDocument`). Both diagnostic logs remain. The corrected measured
  run uses the existing project CLI/expect plus only the external coverage provider,
  and all 140 unchanged tests pass. Initial zero reports are explicitly invalid and
  excluded, not actual 0% coverage.
- Docker was initially stopped: the first ten loop entries in `results.json` are
  preflight failures, no browser execution. Docker Desktop was started without
  resetting any shared container/index. The first three fresh-infrastructure attempts
  then failed before collection because this new config was treated as CommonJS
  outside web's ESM package. Replacing import.meta-based path lookup with cwd-relative
  lookup fixed only quality config. These are setup failures, not application flakes.
- Setup failures and their exit 1 remain in raw reports. They are excluded from the
  denominator of actual executed E2E scenarios, not erased or counted as PASS.

No existing application test was demonstrated flaky; no production/test correction
or retry is proposed based on these tooling failures. Additional supported-Node,
real-server contention and adverse-network runs would reduce the stated residual risk.

## Reproduce and review

Use the existing backend environment at `D:/SE/LAE-issue-73/.venv/Scripts/python.exe`.
Runners and every `.log` header record exact commands, working directory and exit
code. `run_quality.py` orchestrates trace/order/race/shuffle/coverage and ten browser
runs. Prerequisites: running Docker, pinned cached image, installed Chrome, project
web dependencies and the matched coverage provider. Archive this directory before
reproduction: log names are fixed and per-run E2E directories refuse replacement.

No project dependency was installed. Development tools were installed externally:
`npm.cmd install --prefix D:\SE\vt013-quality-tools --no-save --package-lock=false @vitest/coverage-v8@5.0.3 vitest@5.0.3`.
Temporary junctions reuse existing project jsdom from that prefix and expose the
provider under ignored `web/node_modules/@vitest/coverage-v8`. Package/lock files
are unchanged; these tool paths are outside committed source. The final coverage
command must use `web/node_modules/vitest/vitest.mjs`, not the standalone temp CLI.

`python-coverage-correction.json`, `frontend-coverage-correction.json`, and the E2E
repetition JSONs supplement the original failed orchestration's raw `results.json`.
The latter remains an honest record of its setup failures, not an overall PASS claim.
`final-summary.json` consolidates actual verified counts, coverage and integrity.
Git diff checks, HEAD, source hashes and prior-evidence preservation are checked at
the end. No new secret or real project data belongs in the evidence. Stop for review.
