# VT-013 real Undo performance — NOT MET

Branch: `feat/vt013-undo-manhpd`; unchanged HEAD
`d899b960ea898d841a54a3d091019603e3768337`. This is a benchmark result, not a backend
optimization. Production, existing tests, contracts and dependency files are unchanged.
No commit, push, merge or PR was performed. Raw generated evidence remains untracked.

## Actual comparison

`comparison.csv` is the performance comparison table with all requested statistics;
`summary.json` is its machine-readable source. Each class is evaluated independently:

- **0 messages — NOT MET:** 1,140 measured attempts (planned 3,000), 1,139 HTTP 200,
  one client ReadError, no HTTP conflicts/errors and no timeouts. Successful p50
  **1,117.262 ms**, p95 **2,097.897 ms**, p99 **2,157.412 ms**, max **2,164.802 ms**,
  mean **1,536.484 ms**. The p95 already exceeds 2,000 ms, and zero-error criteria
  also fail. This is a partial workload, not a completed 3,000-request claim.
- **2 messages — NOT MET:** **3,000/3,000 HTTP 200**, zero errors/timeouts/conflicts,
  successful p50 **1,072.561 ms**, p95 **2,077.965 ms**, p99 **2,116.264 ms**,
  max **2,964.032 ms**, mean **1,485.834 ms**; **28.590 requests/s** in active Undo windows.
- **100 messages — NOT MET:** **3,000/3,000 HTTP 200**, zero errors/timeouts/conflicts,
  successful p50 **1,941.804 ms**, p95 **2,602.975 ms**, p99 **3,168.852 ms**,
  max **3,594.108 ms**, mean **1,790.484 ms**; **24.439 requests/s** in active Undo windows.

Totals: **7,140 measured Undo attempts**, 7,139 successes and one network error;
**900 warm-up requests** are recorded separately. All 7,139 successful measured
responses passed exact persisted-state restoration checks. The failed request did
not have its restoration postcondition confirmed; it is not a corrupted successful
Undo and is not evidence that existing history was overwritten.

Percentiles use **nearest rank on all individual successful measured samples per
class**, never averages of per-round percentiles. Warm-ups are retained but excluded
from latency/SLO statistics. Failures are retained with latency/error/status and
state checks; successful latency is not mixed with errors or contention conflicts.
`max_all_attempts_ms` and failure counts are separate fields. There were no client
timeouts to omit. Header/connection scheduling and response decoding are included
after each worker leaves the barrier; time waiting to be scheduled before starting
its timer is excluded. Throughput is measured requests divided by summed active
round wall times, **not** whole experiment throughput including setup.

## Why history 0 stopped early

`samples.jsonl` contains the entire initial run: five warm-up rounds and 19 measured
rounds, each 60 tasks. At global round 23 (measured round 18), `vt013-0-57` received
`ReadError` at **826.983 ms** and its subsequent restored-state predicate was false.
The harness stopped before re-arming that contaminated baseline; silently appending
another Send would have changed the workload. All 1,440 samples remain, including
the error. Root `results.json` records the failure and owned-resource cleanup.

The original harness stopped the whole experiment at that assertion and only saved
round wall-time aggregates after a completed class. Consequently **history-0 active
window throughput was not retained and is NOT AVAILABLE**; it is not reconstructed
from maximum latencies. Failed request exception text/raw document were also not
saved in that initial version; its boolean postcondition and error type are retained.
Root cause of this transport failure is therefore **undetermined**, not attributed
to a production bug without more evidence. No automatic retry was used to erase it.

A harness-only correction now stops just the affected class, records its reason
and saves a raw incorrect-state document on future failures. The continuation used
fresh infrastructure and explicitly selected histories **2,100**. Those completed
all five warm-up and 50 measured rounds. There was no second history-0 run, no discarded
slow request, and no threshold, server, pool or client timeout tuning between runs.
Actual reductions and their reason are present in the comparison table.

## Measured task and preparation

The workload/protocol was explained before implementation. Existing `load-tests/`
uses Locust for ingestion/search; it has no existing Undo workload and assumes
deployment credentials. This separate stdlib ThreadPoolExecutor/httpx harness reuses
the already installed project dependencies to provide precise 60-way barriers,
owned infrastructure and retained per-request samples without new dependencies.

One timed task is an authenticated real HTTP POST to
`/assistant/clusters/{id}/conversation/undo`, waiting for the response and decoding
JSON. It starts after a **61-party barrier** (60 worker tasks plus coordinator).
The client has 60 connection slots and 60 keep-alive slots, timeout 40 s, no added
mutation retry. No tracing, coverage or fake persistence runs during timing.

Outside timing: Docker/API readiness, seeding a real admin, `/auth/login`, index
creation, initial histories, **real Send for every re-arm**, obtaining the resulting
server-issued revision, and raw OpenSearch reads checking every restoration. The
client never invents a revision to send; formatting raw metadata is used only as an
assertion against the response. Preparation/verification errors are not latency samples.

Each measured round uses 60 independent conversations in a single test-specific
conversation index. Every successful Send must return exactly H + T and an available
snapshot. Every Undo response and raw source must restore exactly H, consume the
snapshot and advance revision. A revision is taken from each round's actual Send,
not reused from an earlier round. All non-null history/generated message contents
are 1,024 UTF-8 bytes. The 100-message case includes a null assistant tool-call
message and Unicode/tool data. Content is deliberately repetitive/compressible;
this is not a high-entropy or arbitrarily nested real-log workload.

Measured response bodies were 83–84 bytes for empty history, 2,275–2,276 bytes for
two messages and 108,843–108,844 bytes for 100 messages. Request body sizes and
response sizes are retained per class; request sizes are computed compact JSON
body bytes, not full headers/TCP wire sizes.

## Isolation, environment and resources

Both runs used newly labelled disposable `opensearchproject/opensearch:2.17.1`
containers with random loopback-only host ports, no shared/bind data volume, and
owned tmpfs data. Exact cluster name/version is checked before writes. All index
names begin with the unique `vt013-perf-<run-id>` prefix; cluster IDs are test-specific.
No existing/shared index is deleted, reset or targeted. Final removal is only the
exact owned container ID after checking its label. Credentials/JWTs stay in memory
and child environment, not in reports or raw samples. OpenSearch security is disabled
only on these disposable nodes; Query API admin authentication remains real.

Host: Windows, **12 logical processors**, **16,890,519,552 bytes physical RAM**.
Docker engine/client versions, server build, Python and package versions are in
`docker-version.log`, `host-resources.log` and both results JSONs. API uses the existing
Python development interpreter, **Python 3.14.6**, not the earlier Python 3.11 Docker
verification runtime. One Uvicorn API worker; OpenSearch one node, one shard, zero
replicas, **512 MiB JVM heap**, **2 GiB container limit**, 1 GiB data tmpfs. No backend
setting was optimized to meet the target.

Docker CPU/RAM snapshots are in `resources-*.log` and continuation equivalents;
resource samples occur outside timed rounds and are not continuous peaks. Host
Python launcher/child observations are in `api-resource-observations.jsonl`: the venv
launcher alone reports almost no CPU/RAM, so the real Python child was also sampled.
These are point/cumulative observations, not whole-run utilization or a CPU profile.
Early attempts to sample the first process occurred after it had exited and produced
no measurement. The machine is shared with ordinary host activity; CPU affinity,
background load and dedicated-machine isolation were not controlled.

## Likely bottlenecks — inference, not a demonstrated fix

`storage.py:141,144` performs every write with `refresh="wait_for"`. The actual index
settings captured in `continuation/conversation-settings.json` report a **1s refresh
interval**. The Undo route is synchronous (`router.py:135`); the installed AnyIO
asyncio backend's default limiter is **40 tokens** (`_asyncio.py:3257`), below the 60
simultaneous tasks. Roughly 1–2s response clusters are consistent with refresh waiting
and queued synchronous work. This is source/settings evidence and a plausible
explanation, not profiler proof of causality. Large histories additionally require
schema traversal, copying, serialization and a roughly 109 kB response; observed
history-100 p95 is higher. Their individual contributions were not isolated.

No refresh interval, thread limit, worker count or conditional write was changed.
Production SDK retries remain unchanged; internal attempts were not separately
instrumented. The ReadError needs separate client/server/network diagnostics before
assigning root cause. Do not trade away durability/CAS to obtain a lower p95 without
a new reviewed experiment.

## Separate real contention correctness

The continuation also executes **Undo/Undo** and **Send/Undo** against the same
eligible conversation, in separate API processes after the benchmark. It reuses the
reviewed real-read barrier from the integration test server: both handlers receive
the same real persisted version before either conditional write. No response or
OpenSearch transport is mocked. Only AI generation is deterministic.

Each pair returned **one 200 and one 409**. Undo happened to win in both observed
pairs; a predetermined thread identity is not guaranteed or required. The expected
state is computed for the actual successful operation and compared with both its
response and raw persisted messages/snapshot. Full final documents and winning
operation are in `continuation/results.json` and `summary.json`. These two conflicts
are not included in the independent-conversation latency distribution. This closes
the previously identified real Send/Undo race gap for this one executed interleaving,
not for all possible failures/schedules.

## Reproduce and verify

Initial full-protocol command (actual exit 1 on the recorded network failure):

```powershell
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B load-tests/vt013_undo.py
```

Explicit continuation (actual exit 0; completion does not mean SLO MET):

```powershell
$env:VT013_PERF_OUTPUT='D:\SE\Log-Anomaly-Explorer\docs\assignments\VT-013\evidence\performance\continuation'
$env:VT013_PERF_SIZES='2,100'
& 'D:\SE\LAE-issue-73\.venv\Scripts\python.exe' -u -B load-tests/vt013_undo.py
python -B docs/assignments/VT-013/evidence/performance/summarize.py
```

Archive output first; the harness refuses to overwrite samples. On a fresh full run,
clear the two environment overrides to use the default 0,2,100 protocol. It reuses the
existing test-only API lifecycle helper, substituting only a benchmark server entry
point for 1 KiB deterministic generation. Real routes/storage/authentication are
unchanged. All startup/cleanup command argument arrays and exit codes are in logs.

Existing relevant backend regressions ran **after** measurement/cleanup: **90/90 PASS**,
exit 0 (`backend-regression.log`, JUnit, `regression-results.json`). They did not run
concurrently with timed workload. `process-cleanup.json` confirms the known API
launchers/workers and descendants are absent; both owned containers were removed.
Git diff checks and source integrity are recorded in `review.json`. No previous
test assertion or production source is changed, no live Azure call occurs, and no
performance result is inferred from earlier fake or browser tests. Stop for review.
