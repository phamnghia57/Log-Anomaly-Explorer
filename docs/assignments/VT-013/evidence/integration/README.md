# VT-013 VERIFY — real OpenSearch integration

## Outcome actually executed

**Backend ready for the next implementation stage, within the limits below.**
No production compatibility bug was discovered and no production correction was
made. This is not performance, mutation, frontend or deployment verification.

- Branch: `feat/vt013-undo-manhpd`.
- HEAD: `4487c1d93c77c117b1c18c0f611cd76152e3a011`.
- Original assignment baseline: `a2e0c070d694054001767979fe3f247e7ebff6be`.
- Host Python 3.14.6: **13/13 real-instance integration cases PASS**, exit **0**;
  **90/90 existing backend cases PASS**, exit **0**.
- Actual Query API Dockerfile: **build PASS**, exit **0**.
- Network-disabled runtime schema import as `appuser`: **PASS**, exit **0**.
- Built image's Python 3.11.18: **103/103 PASS**, exit **0**, comprising the same
  **13 real-instance integration cases plus 90 fake-based backend regressions**.
  These are repeat executions, not 206 distinct cases or 103 real-server cases.
- No final test failures, collection errors or skips. One existing Starlette
  deprecation warning about its httpx-based TestClient is retained in the logs;
  it did not prevent execution. No dependency change was made to address it.
- Both disposable OpenSearch containers, including the first diagnostic attempt,
  were removed after verifying their exact IDs and ownership labels.
- `git diff --check` passed. Task-start integrity is recorded in `integrity.json`;
  the later checkpoint's selected-file hashes and checks are in
  `../checkpoint/manifest.json`.

Results and exact command argument arrays: [results.json](results.json).
Per-case results: [test-results.md](test-results.md).
Source review, concurrency invariant, client compatibility and gaps:
[review.md](review.md). Full reviewed production diff:
[reviewed-production.diff](reviewed-production.diff).

## Environment and isolation

Docker Desktop/Engine 29.9.2 was already installed; its initially stopped daemon
was started. The pinned OpenSearch image was already cached. No host dependency
was installed and no shared compose stack or project `.env` was used.

- OpenSearch: **2.17.1**, server build hash
  `1893d20797e30110e5877170e44d42275ce5951e`, verified from the actual root API.
- Image: `opensearchproject/opensearch:2.17.1`; inspect output and image ID are
  captured in `opensearch-image.log`.
- Final cluster: `vt013-integration-b747e02ce8644bf9`; its exact owned container
  ID is recorded in `instance.json` and the inspect/cleanup logs.
- Host endpoint is recorded in `instance.json`. It was a random **127.0.0.1-only**
  port, not the project's normal 9200 endpoint. It is no longer live after cleanup.
- One disposable node, JVM 512 MiB, container memory limit 2 GiB, data in owned
  tmpfs; no project data directory or shared data volume was mounted.
- Every test creates fresh `vt013-<run-id>-<case-id>-*` indexes for conversations,
  clusters, history, users, logs and quarantine. No index DELETE/reset is issued.
  The missing-index test targets a never-created name; it does not remove an index.
- The fixtures verify exact cluster name and version before writing. Python 3.11
  tests share only this container's network namespace and use fresh index names.
- API servers are separate tracked OS processes, stopped individually. Restart
  tests launch a second PID against the same index without resetting its data.
- Actual admin hashing, stored admin account, `/auth/login` and JWT verification
  run; no dependency override or permissive auth fake is used. Ephemeral passwords
  and JWTs are not saved in evidence.
- Generation returns a fixed message pair in a test-only server entry point.
  All persistence operations use the actual repository, SDK and server. Concurrency
  coordination wraps actual reads or generation with barriers; it synthesizes no
  persistence responses. Sleeps are used only for bounded server readiness polling.

Host and Docker runtime both used `opensearch-py 3.2.0`, FastAPI 0.162.2,
Pydantic 2.14.3 and jsonschema 4.26.0. Host pytest is 9.2.0, Starlette 1.10.0,
httpx 0.28.1. The Docker runtime probe additionally records uvicorn 0.54.0.
Version/build logs, actual SDK 404 shapes, mappings, final `_source` and version
metadata are retained rather than inferred from the earlier fake suite.

## Contracts covered

The 13 cases cover all ten requested critical contracts:

1. I-01 creates a conversation with Send, completes another Send, then Undo/GET;
   final persisted messages equal the first completed turn.
2. I-02 restores exact Unicode, ordered tool messages, null content, empty content,
   tool-call data and timestamps. Creation time remains unchanged.
3. I-03 undoes the first Send to a **persisted** empty array with a new revision;
   stale and repeated Undo return 409 and leave the document/version unchanged.
4. I-04 terminates the API process, starts another, and verifies GET plus raw
   OpenSearch document equality after restoration.
5. I-05 runs both initial create-only and existing-document Send races. A barrier
   forces both requests to use the same read version: one 200, one 409, one commit.
6. I-06 synchronizes two real reads before Undo CAS writes: one 200, one 409,
   exactly one restored history and consumed snapshot in persisted storage.
7. I-07 captures real missing-document/missing-index SDK exceptions, checks the
   actual repository and HTTP 503 behavior, and verifies no AI call or new data.
8. I-08 creates the original strict mapping without `undo`; real API startup adds
   only that field, preserving old properties and data. An unexpected root field
   still receives an actual OpenSearch HTTP 400 rejection.
9. I-09 reads a legacy conversation with real metadata and no synthesized Undo;
   Undo returns 409 without changing the document.
10. I-10 uses actual SDK connection refusal to verify read error propagation and
    no history loss/generation; I-11 uses a real index write block to verify Undo
    returns 503 and retains its previous messages, revision and snapshot.

I-12 additionally checks missing admin authentication on all three endpoints,
invalid/blank/overlength/wrong-type inputs, invalid revision boundaries, no invalid
request side effects, and accepted 1/4000-Unicode-code-point messages.

Final persisted documents, mappings and process IDs are under `host-artifacts/`
and `python311-artifacts/`. Tests assert raw persisted state, not only statuses.

## Initial diagnostic failure and correction

The committed `initial-attempt/` subset preserves the first results, test logs,
JUnit, failing test-source snapshot and instance/cleanup command evidence:
**12 passed, 1 failed**, exit **1**. The failure was in the
new test harness: concatenating a base URL without a trailing slash with a stripped
path produced an invalid port such as `63085assistant`. No request reached the
API in that assertion; it is not evidence of a production contract failure.

The correction uses an unauthenticated httpx client with `base_url` and relative
paths. The 401 assertions remain and now cover GET, Send and Undo. No production
code or existing test expectation was changed. The complete suite was rerun in a
fresh disposable instance; final evidence is separate from the initial attempt.
The initial regression run also passed 90/90. Docker/Python 3.11 verification was
not attempted in the initial run because its integration step had failed.

## Reproduce

From the repository root with Docker Desktop running and the pinned image present:

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B docs/assignments/VT-013/evidence/integration/run_integration.py
```

That exact command was executed, final exit **0**. It creates a new unique instance,
runs the targeted tests, builds the Query API, probes the schema, creates a separate
test image with the existing declared `pytest>=8` development dependency, executes
the 103 cases under Python 3.11, reruns the existing 90 cases on the host, captures
logs/JUnit, and removes only the owned OpenSearch container. Test files are mounted
read-only; evidence is mounted writable. Build images remain in Docker's local
cache under unique `vt013-query-api*:<run-id>` tags.

Detailed subprocess commands and exit codes are in the corresponding `.log`
headers and `results.json`. The main targeted command is pytest against
`tests/test_assistant_undo_integration.py`; it requires the runner's live owned
instance/context. Direct collection without that opt-in context skips those tests
and **does not constitute verification**. Do not reuse archived instance manifests
as if the removed containers were still live. Copy/archive this evidence directory
before rerunning if historical results must be retained.

On another machine, an existing environment satisfying `query-api/requirements-dev.txt`
can replace the interpreter path. If the pinned image is absent, pulling it is a
setup step to perform separately; no pull was required during this execution.
This Windows sandbox blocks parts of local socket handling, so the recorded runs
used approved execution outside that sandbox. Import failures, skips or readiness
timeouts must be reported separately from executed contract assertions.

## Remaining verification

NOT VERIFIED in this phase: frontend; swallowed-exception mutation; 60 concurrent
tasks/p95 ≤ 2.0 s; live Azure/tool generation; TLS/OpenSearch security plugin;
OpenSearch restart/replica failover; lost-response/timeouts and SDK retries;
minimum `opensearch-py 2.6` or all future unconstrained dependency versions.
Real mixed Send/Undo interleaving is not added; the existing backend suite covers
it using the transport fake. See `review.md` for the practical implications.

During VERIFY, changes were limited to two new integration test/helper files and
this evidence directory. The approved plan, RED/GREEN evidence, production files,
existing tests and unrelated untracked files were preserved. No frontend,
mutation, performance, commit, push, merge or PR action was performed during that
phase. A subsequent user-authorized checkpoint commits the reviewed backend and
selected evidence; its exact file scope is recorded separately.

For that checkpoint, verbose OpenSearch server logs, empty API logs, generation
event dumps, repeated local diff-audit files and duplicate initial-attempt files
are intentionally left untracked. They remain on the original machine. Committed
evidence retains final test logs/JUnit, versions/build/schema probes, ownership
checks, raw synthetic persisted documents, mappings and process IDs. These are
disposable test fixtures, not project or production data. The runner still emits
the full local diagnostics on reproduction; the checkpoint manifest identifies
the curated historical subset.
