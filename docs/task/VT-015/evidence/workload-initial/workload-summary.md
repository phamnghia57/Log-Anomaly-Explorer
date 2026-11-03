# VT-015 simulated HTTP workload

**SIMULATED backend; not production performance.**

One API subprocess; loopback HTTP; 80 client threads for each 80-request scenario.
SQLite unique-key transactions exercise the actual ApprovalRepository. Cluster reads are
an isolated in-memory fixture. No OpenSearch transport/sharding/replication is modeled.
Hardware is recorded in hardware.txt. Temporary database was removed after validation.

Requests: 162; successes: 82; conflicts: 80; errors: 0.

| Scenario | Requests / concurrency | 201 | 409 | Persisted | Valid |
|---|---:|---:|---:|---:|---|
| same_cluster_2 | 2 / 2 | 1 | 1 | 1 | True |
| same_cluster_80 | 80 / 80 | 1 | 79 | 1 | True |
| independent_clusters_80 | 80 / 80 | 80 | 0 | 80 | True |

Nearest-rank percentiles in milliseconds, separated by response status.
Monotonic perf_counter_ns spans client send to full response receipt, including queueing.
Barrier waiting and API startup are excluded. No approval warm-up requests were sent.

| Scenario | Response | n | p50 | p95 | p99 | Max | p95 < 2500 ms |
|---|---|---:|---:|---:|---:|---:|---|
| same_cluster_2 | success | 1 | 19.543 | 19.543 | 19.543 | 19.543 | True |
| same_cluster_2 | conflict | 1 | 29.348 | 29.348 | 29.348 | 29.348 | True |
| same_cluster_80 | success | 1 | 131.032 | 131.032 | 131.032 | 131.032 | True |
| same_cluster_80 | conflict | 79 | 274.288 | 425.780 | 457.941 | 457.941 | True |
| independent_clusters_80 | success | 80 | 1183.751 | 1654.569 | 1703.811 | 1703.811 | True |
| all | success | 82 | 1169.087 | 1654.569 | 1703.811 | 1703.811 | True |
| all | conflict | 80 | 269.277 | 423.597 | 457.941 | 457.941 | True |

Only one batch per scenario; percentiles (especially n=1) have limited statistical strength.
Compare the 80-task rows to the 2.5-second threshold; aggregate mixes scenarios.
These values do not establish a production SLO or OpenSearch concurrency correctness.
Reproduce: `.venv-vt015/Scripts/python.exe query-api/tests/vt015_workload.py`.
