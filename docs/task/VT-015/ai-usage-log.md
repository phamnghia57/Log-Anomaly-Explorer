# VT-015 AI usage log

This is an activity log reconstructed from the actual conversation, repository
diffs, commits and retained output. Codex assisted with implementation, tests,
commands and documentation under user direction. It is not a claim that a student
performed every action independently, nor a record of evaluator approval. No
external model/version attribution beyond the available Codex agent is inferred.

| Stage | User-directed task and AI contribution | Checks / actual outcome | Evidence / revision |
|---|---|---|---|
| Planning and RED design | Decision table for reviewer reads, immutable originals, missing/invalid credentials, duplicate/concurrent approvals and unavailable storage; tests use a repository seam | Baseline 237 passed; RED 14 failed/8 passed. No production implementation in RED | [decision table](decision-table.md), [RED output](evidence/red-pytest.txt); `a4f13a37942606572f98c70fe5df05bedd7d0868` |
| GREEN patch | Implemented reviewer role/login, restricted Assistant, approval routes and separate create-only repository | 22 RED-contract tests passed, 237 existing tests passed, 181 focused checks passed | [GREEN review](evidence/GREEN-review.md); `e0c5a4f2600e562bf0e465df300c178b912842d7` |
| Post-test patch review | Inspected authorization/storage boundaries and test seams; kept the unrelated contract edit outside staging | Documented missing setup, role-wide permissions, cross-index race and unverified real OpenSearch behavior | [patch review](evidence/PATCH-mutation-review.md) |
| Mutation | Deliberately replaced atomic create with index overwrite on the temporary mutation branch | 1 failed/26 passed; failure was a mocked-client response/call contract mismatch. RED API tests used a double and did not detect it. Defect removed before returning to submission branch | [mutation patch](evidence/mutation.patch), [output](evidence/mutation-pytest.txt); evidence in `b627243c1f71a9417b581b2bc9e09a3f3a935a85` |
| Flaky-test investigation | Ran ten independent concurrency repetitions and shuffled collection; reproduced fixture state loss with two tests; changed supplemental fixture to patch State's backing mapping | Concurrency 10/10 passed; shuffled run initially 258 passed/6 setup errors, then 264 passed after fix | [minimal before/after](evidence/shared-state-minimal-before.txt), [shuffled after](evidence/shared-state-shuffled-after.txt); `b627243c1f71a9417b581b2bc9e09a3f3a935a85` |
| Coverage and focused checks | Installed pytest-cov in existing venv, measured line/branch coverage, added 10 input/authorization/storage tests | Full suite 274 passed; missing arcs recorded. No decoder mocks were added solely to inflate percentages | [coverage review](evidence/COVERAGE-concurrency-performance.md), [coverage JSON](evidence/coverage-final.json); `0ae83dc5c70dab310fe78d6d31ff7aae66db2342` |
| Concurrency/performance | Checked local Docker/OpenSearch; built SQLite transaction adapter for the actual repository; used HTTP to one separate API process | Default OpenSearch refused connections; simulated 2/80 contenders had one winner; 80 distinct IDs succeeded. Standalone independent-approval p95 1.471 s, conflict p95 0.828 s; no production SLO claim | [availability probe](evidence/opensearch-probe.json), [CSV](evidence/workload-raw.csv), [summary](evidence/workload-summary.md); `0ae83dc5c70dab310fe78d6d31ff7aae66db2342` |
| Submission preparation | Audited real setup gaps; added explicit reviewer/index setup, schema alignment and 24 tests; wrote README, traceability, this log, reflection draft and evidence index | Setup tests 24 passed; final suite 298 passed. No live OpenSearch setup, push, merge, PR or PDF performed | [setup review](evidence/submission-setup-review.md), [final output](evidence/submission-pytest.txt); submission commit resolved as described in [evidence index](evidence-index.md) |

## Review findings and decisions

**Evidence-supported finding - accept and fix.** The GREEN supplemental test
`test_vt015_green_regression.py::test_reviewer_login_and_assistant_denial` patched
Starlette State with `monkeypatch.setattr`. Teardown deleted
`assistant_conversations`, so the next Assistant fixture raised AttributeError.
The [two-test reproduction](evidence/shared-state-minimal-before.txt) produced one
setup error. Patching the backing dictionary with `monkeypatch.setitem` restored
the original value. The same [sequence passed](evidence/shared-state-minimal-after.txt)
and the shuffled suite passed after the fix. Decision: accept the finding and the
test-only repair; reject a production workaround for a fixture defect.

**Plausible but unsupported finding - reject as established fact.** The suggestion
that approvals would definitely fail in production because index auto-creation was
disabled lacked deployment settings or a live OpenSearch probe. The prior
`ApprovalRepository` had no initializer, which established a provisioning gap, but
did not prove that any production instance disabled auto-create. Decision: reject
the unconditional failure claim; keep the deployment assumption explicit. The
current task authorizes explicit setup, so `ApprovalRepository.ensure_ready` and
`setup_reviewer` now address that gap without assuming a live configuration.

## Human responsibility and boundaries

The user directed phase boundaries, scope and preservation of the unrelated API
contract edit. AI-generated changes were checked through diffs and executed tests;
human review of code, academic authorship, reflection wording and submission rules
is still required. The Vietnamese reflection is labeled as a draft for the student
to verify. Local measured results are reported with their simulation limitations.
No PDF, PR, merge or push is part of this log.
