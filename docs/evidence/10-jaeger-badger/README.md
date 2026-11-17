# Task 10 / Issue #107 — Jaeger Badger evidence

This directory contains real local validation for
[Issue #107](https://github.com/phamnghia57/Log-Anomaly-Explorer/issues/107).
Production was not restarted. No volumes were deleted. The 24-hour observation is
**PENDING**; there is no 24-hour measurement or screenshot claimed without a capture.

## Environment and version gate

- Base commit: `b083a3ead2ee620c5df5e05f5dfa2d9bcf2dbcce` (`origin/main` when work started).
- Raw timestamps are UTC; local operator time is Asia/Saigon (UTC+7).
- Docker Desktop, Linux/amd64 engine 29.9.2; resource allocation in `docker-host.json`.
- Dedicated Compose project `lae107`, with its own network and named volumes.
- Loopback ports: ingestion 18000, demo 18001, query 18002, Jaeger 26686,
  gateway 18080/18443, test OpenSearch 19200, frontend 15173.
- Temporary credentials/configuration live outside the repository. Webhooks,
  dead-man-switch pings, Azure OpenAI and Langfuse were disabled for this test.
- Image: `jaegertracing/all-in-one:1.76.0@sha256:ab6f1a1f0fb49ea08bcd19f6b84f6081d0d44b364b6de148e1798eb5816bacac`.
- Running the image's `version` command before editing returned **v1.76.0**,
  git commit `63b27e1810a710ac54dc4522da0538e540bdc545`, build date
  `2025-12-03T16:07:08Z`. See `jaeger-version.txt` and `image-metadata.json`.
- `jaeger-badger-flags.txt` is an excerpt of actual `--help` output with
  `SPAN_STORAGE_TYPE=badger`. The image runs as UID 10001; `jaeger-init` prepares
  only the three Badger directories, then exits before the Jaeger writer starts.
- The v1 binary reports its upstream end-of-life notice. Its version/digest is
  retained as required by this issue; a v2 migration is outside this change.

Official references: [1.76 deployment](https://www.jaegertracing.io/docs/1.76/deployment/),
[1.76 CLI flags](https://www.jaegertracing.io/docs/1.76/deployment/cli/),
[v1.76.0 Dockerfile](https://github.com/jaegertracing/jaeger/blob/v1.76.0/cmd/all-in-one/Dockerfile).

## Validation results

- **PASS** — 18 static checks, including default/empty/24h TTL interpolation,
  immutable image, OTLP and query base path, named volume/init dependency,
  removal of memory settings, and unchanged unrelated services/volumes.
  Details: `static-validation.json`.
- **PASS** — query-api: 331 passed; 7 live tests skipped in the unit run were
  subsequently run explicitly against the dedicated OpenSearch and all 7 passed.
  The targeted assistant suite passed all 53 tests.
- **PASS** — demo-app 53, ingestion 27, clustering 67, load-tests 24 tests passed.
- **PASS** — frontend lint/build, 133 unit tests; browser suites: real OpenSearch
  auth 9 passed, mock auth 8 passed/1 conditional skip, system integration 12 passed.
- **PASS** — existing CI-style Locust smoke: 3 users, 30 seconds, 204 requests,
  0 failures, exit code 0. See `load-smoke.txt`, `load-smoke-result.json` and CSVs.
- **PASS** — fresh named volume initialized successfully (exit 0), directory owner
  `10001:10001`, mode 750, effective TTL `168h`; initial disk usage **40 KiB**.
  See `init-state.json`, `badger-mount.json`, `jaeger-effective-env.txt`, `disk-initial.txt`.
- **FAIL** — RAM did increase under the matched workload: memory peak **15.76 MiB**,
  idle median **15.64 MiB**; Badger peak **30.96 MiB**, idle median **30.88 MiB**.
  Both phases completed in 720 seconds, each with 660 expected responses, 64
  Docker stats samples, no network errors and no sampling errors. See
  `workload-memory.json`, `workload-badger.json`, `stats-*.jsonl`, `requests-*.jsonl`.
- **PASS** — the same real trace `a03e347ec32cb97998178a27beee0607`, with 3 spans,
  remained queryable and opened from the actual Incident View link after Jaeger
  restart, full-stack restart and container recreation. The recreated container
  has a different ID. See `runtime-validation.json`, `runtime-commands.txt`,
  `trace-*.json`, and the paired `incident-*.png` / `trace-*.png` screenshots.
- **PENDING** — `du -sh` after 24 hours of operation, required for Task 12.
  The short-run post-test sample is **1712 KiB** (`du -sh`: 1.7M), recorded in
  `disk-after-tests.txt`; this is explicitly not the required 24-hour sample.

Text log trailing whitespace and extra final blank lines were normalized; measured
values, messages and timestamps were not changed.
Logs are named `pytest-*.txt` and `web-*.txt`. The first local attempt exposed a
stale `node_modules` and a local Vite API URL incompatible with test expectations;
`npm ci` and explicit `VITE_API_BASE_URL=/api`, empty `VITE_JAEGER_URL` resolved it
without frontend code changes. A first backend container run inherited its build
SHA; rerunning with `GIT_SHA=unknown`, as expected by the health test, passed.
The Windows unit-test attempt was interrupted during collection; the complete
backend results are from Python 3.11 in Linux containers. Existing lint/build
warnings and an aggregation error logged by the mock system fixture remain in
the logs; that browser suite still completed with 12 passing tests.

The RAM result contradicts the issue's expected saving for this light workload;
disk-backed storage is not a guarantee of smaller RSS. Badger adds index/buffer/cache
overhead, which can dominate a small in-memory trace set. No heap profile was taken,
so this is a plausible explanation, not a measured attribution to a particular
allocation or compaction. No additional cache tuning/version change was introduced
to hide the result. The RAM acceptance remains unmet and needs profiling/tuning
or an explicit owner decision before this Draft PR is considered ready.

## Reproduce in an isolated local project

Use a disposable machine/project and free loopback ports. Never point this test
at production OpenSearch, webhooks or volumes. The following PowerShell setup
uses process-local test credentials and an explicit sample env file, not `.env`.
Keep the same terminal for these commands. Set `$repo` to the repository root.

```powershell
$repo = (git rev-parse --show-toplevel).Trim()
$lab = Join-Path $env:TEMP 'lae107'
New-Item -ItemType Directory -Force -Path $lab | Out-Null
$baseline = Join-Path $lab 'compose-memory.yml'
git show b083a3e:docker-compose.yml | Set-Content -Encoding utf8 $baseline
$override = Join-Path $lab 'override.yml'
@'
services:
  opensearch:
    ports:
      - "127.0.0.1:19200:9200"
  gateway:
    ports: !override
      - "127.0.0.1:18080:80"
      - "127.0.0.1:18443:443"
      - "127.0.0.1:18443:443/udp"
'@ | Set-Content -Encoding utf8 $override
$env:INGESTION_PORT = '18000'
$env:DEMO_APP_PORT = '18001'
$env:QUERY_API_PORT = '18002'
$env:JAEGER_UI_PORT = '26686'
$env:PUBLIC_ADDRESS = ':80'
$env:OPENSEARCH_URL = 'http://opensearch:9200'
$env:OPENSEARCH_HEAP = '512m'
$env:JWT_SECRET = (& python -c 'import secrets; print(secrets.token_urlsafe(48))').Trim()
$env:ADMIN_SEED_USERNAME = 'issue107-admin'
$env:ADMIN_SEED_PASSWORD = (& python -c 'import secrets; print(secrets.token_urlsafe(24))').Trim()
$env:AUTH_COOKIE_SECURE = 'false'
$env:AUTH_ALLOWED_ORIGINS = 'http://127.0.0.1:15173'
$env:CORS_WEB_ORIGIN = 'http://127.0.0.1:15173'
$env:OTEL_EXPORTER_OTLP_ENDPOINT = 'http://jaeger:4318'
$env:JAEGER_QUERY_URL = 'http://jaeger:16686/jaeger'
$env:JAEGER_TRACE_TTL = '168h'
$env:ALERT_WEBHOOK_URL = ''
$env:HEALTHCHECK_PING_URL = ''
$env:AZURE_OPENAI_API_KEY = ''
$env:AZURE_OPENAI_ENDPOINT = ''
$env:LANGFUSE_PUBLIC_KEY = ''
$env:LANGFUSE_SECRET_KEY = ''
$env:GATEWAY_BASIC_AUTH_USER = 'issue107'
$gatewayPassword = (& python -c 'import secrets; print(secrets.token_urlsafe(24))').Trim()
$env:GATEWAY_BASIC_AUTH_HASH = (docker run --rm caddy:2.8-alpine caddy hash-password --plaintext $gatewayPassword).Trim()
$composeFile = $baseline
function dc {
  docker compose --project-directory $repo -p lae107 --env-file "$repo/.env.example" -f $composeFile -f $override @args
}
dc config --quiet
dc up -d --build
```

`!override` requires Compose 2.24.4 or newer (the measured host uses Compose
5.6.1). Ensure `docker ps -a` / `docker volume ls` show no pre-existing `lae107`
project before a new comparison; preserve any existing project rather than
deleting its volumes. Never run `down -v` or reset persistent storage.

### Matched RAM workload

Before either phase, wait for all services and Jaeger API readiness. Avoid other
builds/tests during measurement. `measure.py` uses only Python standard library
plus Docker CLI. Each phase runs 60 warm-up requests, 600 measured requests at a
target 1 request/second and concurrency 1, then 60 seconds idle. Every tenth
request injects a runtime fault: expected statuses are 594 HTTP 200 and 66 HTTP
500 including warm-up. Docker stats are sampled approximately every 10 seconds
plus CLI execution time. Files include raw requests, raw Docker stats and summaries.

```powershell
# Baseline: memory, maximum 20,000 traces, same pinned image.
dc restart jaeger
python "$repo/docs/evidence/10-jaeger-badger/measure.py" memory

# Candidate: recreate Jaeger to apply the new storage/env/mounts.
$composeFile = Join-Path $repo 'docker-compose.yml'
dc up -d --build
python "$repo/docs/evidence/10-jaeger-badger/measure.py" badger
```

Do not run the two workloads concurrently. Each phase overwrites its own evidence
files; copy results to a separate output directory with `--output` for repeat
runs. Compare peak and the median reported memory during the final idle minute.
This is Docker's reported container memory for this workload, not proof about
every production load. Any increase is an acceptance **FAIL**, not a claimed saving.
Badger still allocates memory for indexes, buffers, caches and maintenance.

### Persistence and Incident View

```powershell
dc exec -T query-api python -m query-api.src.manage_auth init
dc exec -T query-api python -m query-api.src.seed_admin
curl.exe -i 'http://127.0.0.1:18001/simulate-error?rate=1&fault=runtime&seed=107'
```

HTTP 500 is expected for this deliberate fault. Wait for OTLP export and the
clustering window/ingestion lag, then obtain the real trace ID from the ingested
log/Incident View. Poll until the Jaeger response has the same ID and non-empty
spans; a successful HTML response alone does not prove trace persistence.

Run frontend with `VITE_API_BASE_URL=/api`,
`API_PROXY_TARGET=http://127.0.0.1:18002`, and
`VITE_JAEGER_URL=http://127.0.0.1:18080/jaeger`:

```powershell
$env:VITE_API_BASE_URL = '/api'
$env:API_PROXY_TARGET = 'http://127.0.0.1:18002'
$env:VITE_JAEGER_URL = 'http://127.0.0.1:18080/jaeger'
npm --prefix web run dev -- --host 127.0.0.1 --port 15173 --strictPort
```

Log in using the disposable admin; open the affected incident and its trace link.
The gateway uses the temporary basic-auth account above. Save real screenshots
before and after each operation, keeping exactly the same trace ID:

```powershell
$traceId = '<real-trace-id-from-log>'
curl.exe -fsS "http://127.0.0.1:26686/jaeger/api/traces/$traceId"
dc restart jaeger
# Wait for readiness, re-query same ID and reopen the Incident View link.
dc restart
# Wait for all health checks; repeat same ID/link checks.
dc up -d --no-deps --force-recreate jaeger
# Verify a different container ID, same volume and same persisted trace.
```

### Initial disk usage and the pending 24-hour sample

Use the actual mount metadata instead of guessing a Windows path:

```powershell
$cid = dc ps -q jaeger
$mounts = docker inspect $cid --format '{{json .Mounts}}' | ConvertFrom-Json
$mount = $mounts | Where-Object Destination -eq '/badger'
$volumeName = $mount.Name
docker inspect $cid --format '{{range .Config.Env}}{{println .}}{{end}}' | Select-String '^BADGER_SPAN_STORE_TTL='
[DateTime]::UtcNow.ToString('o')
docker run --rm --user 0 --mount "type=volume,source=$volumeName,target=/badger,readonly" --entrypoint /bin/sh caddy:2.8-alpine -c 'du -sh /badger; du -sk /badger'
```

Record the initial timestamp/output and repeat on the **same volume** after at
least 24 hours of actual operation with documented traffic. Keep Docker Desktop
running; record sleep/outage gaps. Save `disk-24h.txt` and add the value/delta,
workload and timestamps to the PR for Task 12. No automation or invented value
substitutes for this observation. TTL does not immediately compact all disk files.
The initial sample was `2026-11-17T19:22:41Z` (18 November 2026, 02:22:41 UTC+7).
The earliest 24-hour sample is 19 November 2026, 02:22:41 UTC+7, provided the
stack remains operational. Traffic is not generated indefinitely after the
benchmark; document any subsequent load or idle period rather than treating the
sample as representative production growth.

## Operational limits

- Normal restart/recreate preserves recorded trace data while the named volume survives.
- Old memory traces do not migrate into Badger. Expired or never-collected traces
  can still be absent; absence does not prove the request did not occur.
- OpenSearch Task 04 snapshots do **not** back up this Badger volume. No separate
  trace backup is implemented here; demo traces can be generated again.
- Keep this PR Draft while RAM acceptance fails or any runtime/24-hour evidence
  is missing. Nghĩa should review the `TRACE_NOT_FOUND_HINT` change in `tools.py`.
