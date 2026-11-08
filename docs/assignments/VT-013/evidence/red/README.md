# VT-013 RED phase — executed contract-test evidence

## Baseline and scope

- Branch: `feat/vt013-undo-manhpd`.
- Current HEAD: `29f06e9cff420d87bf255d516dc2982b20f399c2`.
- Production baseline: `a2e0c070d694054001767979fe3f247e7ebff6be`.
- The intervening commit adds only the approved `plan.md`. Production code still matches the specified baseline.
- This step adds tests, a storage-protocol double and reproducible evidence only. The approved plan, existing tests and production code are unchanged. No dependency was installed, and no commit, push or PR was created.

## Existing test conventions inspected

- `query-api/tests/conftest.py` sets the memory backend before application imports and adds the repository root to `sys.path`.
- Its `admin_auth` fixture creates a real signed test JWT and temporarily configures its secret/lifetime. New tests reuse it; authentication dependencies are not bypassed.
- `test_assistant.py` uses FastAPI `TestClient`, replaces `app.state` stores, provides dummy Azure configuration and deterministic generation responses. State is restored explicitly rather than monkeypatching Starlette `State` attributes.
- `test_assistant_storage.py` constructs the real `ConversationRepository` with an `OpenSearchLogStore` wrapping a fake driver. Its existing driver does not model revisions or conditional writes.
- CI runs Python modules separately, using `cd query-api` and `python -m pytest -v`. Existing Assistant tests were executed before and after the new fixture usage below.

The new tests keep the real route, validation, JWT verification, repository and storage-error handler. Only the OpenSearch transport and AI generation are substituted. The principal assertions concern HTTP statuses, public response fields and persisted message history rather than new private helpers or a particular future class layout.

## New tests and actual outcomes

All names below are in `query-api/tests/test_assistant_undo_contract.py`.

| Test name / parameter | Plan ID / AC | Expected contract | Actual outcome |
|---|---|---|---|
| `test_t03_send_response_exposes_revision_contract` | T-03 / AC-01 | Send returns messages, `revision: "1:0"` for the fixture's first write and `undo_available: true` | **FAIL:** response lacks both new fields |
| `test_t03_undo_first_send_persists_empty_history` | T-03 / AC-01 | Undo returns 200; empty history persists; revision advances; Undo becomes unavailable | **FAIL:** `assert 404 == 200`; Undo route is absent |
| `test_t06_whitespace_message_is_rejected_without_side_effects[space]` | T-06 / AC-02 | 422, zero generation, zero writes, no document | **FAIL:** 200, one generation call and one write |
| `test_t06_whitespace_message_is_rejected_without_side_effects[tabs-newlines]` | T-06 / AC-02 | Same rejection contract for tabs/newlines | **FAIL:** 200, one generation call and one write |
| `test_t06_whitespace_message_is_rejected_without_side_effects[nonbreaking-space]` | T-06 / AC-02 | Same rejection contract for Unicode whitespace | **FAIL:** 200, one generation call and one write |
| `test_t11_read_failure_returns_503_and_preserves_history` | T-11 / AC-04 | 503, storage error envelope, no generation/write, full seeded document unchanged | **PASS:** existing repository correctly propagates the injected connection failure |
| `test_t12_missing_index_raises_storage_error_in_actual_repository` | T-12 / AC-04 | Actual repository raises `StorageError` for a missing index | **FAIL:** `DID NOT RAISE StorageError`; returns `None` |
| `test_t12_missing_index_returns_503_not_empty_success[GET]` | T-12 / AC-04 | 503 rather than successful empty history | **FAIL:** 200 instead of 503 |
| `test_t12_missing_index_returns_503_not_empty_success[POST]` | T-12 / AC-04 | 503, no generation or write | **FAIL:** 200, one generation call and one write |
| `test_t14_concurrent_sends_cannot_silently_overwrite[existing-document]` | T-14 / AC-05 | Statuses `[200, 409]`, one commit; winning history retained | **FAIL:** statuses `[200, 200]`, two commits |
| `test_t14_concurrent_sends_cannot_silently_overwrite[first-creation]` | T-14 / AC-05 | Same protection when both read no document | **FAIL:** statuses `[200, 200]`, two commits |

Three infrastructure controls also pass:

- `test_fake_copies_documents_and_does_not_protect_unconditional_writes`.
- `test_fake_enforces_explicit_conditional_and_create_only_writes`.
- `test_fake_preserves_missing_index_exception_and_ignore_semantics`.

These controls are not RED business-feature evidence. They establish that the double copies data, models revisions, honors explicit CAS/create-only arguments and otherwise allows overwrites, as the current production calls do.

The T-03 Undo test obtains the current token from the storage provider's version metadata so it can reach the absent endpoint and report its 404 independently of the missing Send fields. It does not substitute a response fallback. Its companion test requires the complete public Send response, and the Undo test also requires the Send token to match once the endpoint succeeds. Assertions about restored history and the new revision remain present, but are not reached on this RED baseline.

T-14 uses a bounded `Barrier(2)` inside deterministic generation. Both requests have already read their state before either can write. There are no sleeps. The double does not reject a request merely because another request is in flight; conflicts require actual persistence preconditions supplied by production.

## Executed commands and exit statuses

Working directory for each pytest subprocess: `D:\SE\Log-Anomaly-Explorer\query-api`.

Common command prefix:

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B -m pytest -vv --tb=short -rA --color=no -p no:cacheprovider -o faulthandler_timeout=20
```

The evidence runner appends the following arguments. The exact complete command arrays are recorded in each log header and `results.json`.

| Run | Additional arguments | Actual result | pytest exit status |
|---|---|---|---|
| Existing tests | `--junitxml=D:\SE\Log-Anomaly-Explorer\docs\assignments\VT-013\evidence\red\existing-tests.junit.xml tests/test_assistant.py tests/test_assistant_storage.py` | 24 passed | 0 |
| Focused RED | `--junitxml=D:\SE\Log-Anomaly-Explorer\docs\assignments\VT-013\evidence\red\focused-red.junit.xml tests/test_assistant_undo_contract.py` | 10 failed, 4 passed | 1 |
| Combined regression | `--junitxml=D:\SE\Log-Anomaly-Explorer\docs\assignments\VT-013\evidence\red\combined-regression.junit.xml tests/test_assistant_undo_contract.py tests/test_assistant.py tests/test_assistant_storage.py` | 10 failed, 28 passed | 1 |

The combined run executes the legacy tests after the new tests to check that fixture cleanup restores application state. All 24 legacy cases still pass. Every focused failure is a requested-contract assertion failure; there are no import, collection, fixture or synchronization errors, skips or xfails in these completed runs.

## Reproduce

From the repository root, using the already installed interpreter:

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B docs/assignments/VT-013/evidence/red/run_red.py
```

The command deliberately returns exit status 1 while the feature contracts remain RED. It regenerates the existing/focused/combined logs, JUnit files and results JSON in this directory. On another machine, choose an existing interpreter containing the project's `query-api/requirements-dev.txt` dependencies; the runner uses its own interpreter and does not install packages.

For an individual test, use the common prefix above and append its node ID, for example:

```powershell
$env:STORAGE_BACKEND = 'memory'
$env:OTEL_EXPORTER_OTLP_ENDPOINT = ''
$env:LANGFUSE_TRACING_ENABLED = 'false'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B -m pytest -vv --tb=short -rA --color=no -p no:cacheprovider -o faulthandler_timeout=20 'tests/test_assistant_undo_contract.py::test_t11_read_failure_returns_503_and_preserves_history'
```

Run that individual command from `query-api`. The full runner also removes inherited Langfuse credentials from its child environment, disables bytecode/cache writes and avoids automatic third-party pytest plugins. It does not print credentials or JWTs.

## Environment and infrastructure limitations

- Existing interpreter: `D:\SE\LAE-issue-73\.venv\Scripts\python.exe`; no files in that worktree were edited.
- Actual runtime: CPython 3.14.6, pytest 9.2.0, FastAPI 0.162.2, Starlette 1.10.0, HTTPX 0.28.1, Pydantic 2.14.3, OpenSearch client 3.2.0. All inspected versions are in `results.json`.
- CI declares Python 3.11. This evidence is from the available Python 3.14 environment; it is not a Python 3.11 CI result.
- The ordinary default interpreter lacks required API dependencies. The pre-existing sibling-worktree environment supplied them; no installation was performed.
- Sandbox execution hung during TestClient event-loop initialization: Windows `socket._fallback_socketpair` blocked in `accept`. The separately captured probe timed out after 40 seconds, before assertions. Its JSON records `exit_code: null` and `timed_out: true`; it is **not valid RED assertion evidence**.
- The completed test runs were executed outside that sandbox and did not time out. No production change or test monkeypatch was used to repair Windows socket behavior.
- The current dependency stack emits one Starlette HTTPX deprecation warning. It did not prevent execution, and dependencies were left unchanged.
- Storage transport is a protocol fake, not a real OpenSearch server. The fake does not prove mapping migration, distributed concurrency, restart durability or real transport compatibility; those remain future integration work.

To reproduce only the separate sandbox probe in the affected environment:

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B docs/assignments/VT-013/evidence/red/run_red.py --sandbox-probe
```

## Evidence files and interpretation

- `existing-tests.log` and `existing-tests.junit.xml`: unchanged legacy tests.
- `focused-red.log` and `focused-red.junit.xml`: actual failures and passes of the new slice.
- `combined-regression.log` and `combined-regression.junit.xml`: new tests followed by legacy cases.
- `results.json`: interpreter, versions, branch/HEAD, source/spec/test hashes, commands, process exit statuses and per-case outcomes.
- `sandbox-probe.log` and `sandbox-probe.json`: the separately classified environment blocker.
- `run_red.py`: bounded, reproducible execution and evidence capture.

Captured terminal line endings and trailing display whitespace are normalized for portable text diffs. Assertion values and expected-versus-observed behavior are retained; JSON/JUnit include structured outcome information.

This is a valid initial RED slice: ten executed cases fail for missing or incorrect requested behavior. T-11 already satisfies the specified failure-propagation behavior and is not forced to fail. Successful first-Send restoration cannot yet execute beyond the absent Undo route. No implementation, mutation experiment, real OpenSearch integration, coverage, flaky-test campaign or performance verification is claimed in this phase.
