# Issue #98 — 03a: reproducible synthetic timeline

03a supplies data and labels for Nam's 03b replay/sweep. It does not select new
deployment thresholds or claim production precision/recall. The live harness
`fresh_run.py` and historical 23 October evidence remain unchanged.

## Generate from the repository root

```sh
python -B -m clustering.evaluation.generate_timeline --seed 98 --output /tmp/issue98-seed98
```

On Windows use a new directory such as `D:/SE/tmp/issue98-reproduction`. Output
must not already exist: old runs are never overwritten. Python 3.11 matches CI.
Generation needs only standard library and the existing normalizer: no Docker,
OpenSearch, Jaeger, scikit-learn, network calls or real-time wait.

Defaults: seed 98, fixed start `2026-01-01T00:00:00Z`, 180 minutes, 30-minute warm-up,
two services (`demo-web`, `demo-mobile-api`). Evaluation covers `[00:30,03:00)`.
Start must include a timezone and align to a minute; it is normalized to UTC.
Random streams use stable SHA-256 seeds, not Python's randomized `hash()`.
No current timestamp or output path enters the three reproducible output files.
The issue98 run attributes keep those three JSON files in LF form even on
Windows Git checkouts with `core.autocrlf`, preserving the published byte hashes.

Background errors form a Poisson process per service/fault, sampled through
exponential inter-arrival times, default one error/minute. Override common or
individual rates (errors per minute per service):

```sh
python -B -m clustering.evaluation.generate_timeline --seed 98 \
  --background-rate 0.5 --fault-rate timeout=2 --output /tmp/issue98-alternate
```

Five faults match the existing harness: value/422, connection/502, runtime/500,
timeout/504, downstream/500. Timeout and downstream retain `error_type=runtime`.
`bad_schema` is excluded: it is invalid/quarantined input, not a valid log
delivered to this detector.

There are 10 scheduled incidents: two 5-minute steps, two 5-minute ramps
(2/4/6/8/10 extra errors), two single-window spikes, two new families without
history, and two 3-minute bursts in the same family separated by four minutes.
They add exactly 276 errors; background counts depend on seed/rates. Exact offsets
and per-minute counts are in config. Intervals are half-open `[from,to)`, aligned
to 60 seconds. The first incident starts at minute 40.

Messages vary order ID, latency, hostname and UUID, plus two phrasings per family.
Finite variants leave multiple normalized templates, giving TF-IDF work beyond
number normalization. Ground truth comes from the schedule, never predictions.
Background errors are not labeled as incidents because an anomaly score is high.

## Output and replay contract for Nam

- `logs.json`: JSON array, one record per line; valid shared log schema, no outer
  `log_id`. Trace/span IDs are deterministic and unique within a run. They are
  synthetic IDs, not captured spans that can be opened in Jaeger.
- `labels.json`: legacy incident keys plus fault, family, shape, injected count
  and `expected_cluster_signatures`. Aliases cover only the declared family,
  including possible canonical variants from baseline; not other fault families.
  The singular signature field remains for compatibility.
- `config.json`: seed, start/end, rates, schedule, counts, window/history settings.
- Warm-up/evaluation bounds and `quiet_intervals` are explicit. Quiet means no
  incident in **any** service, excluding warm-up: 114 minutes by default.
  A per-service quiet metric would need its own documented denominator.

Use the adapter before offline replay. It adds stable IDs on copies without
polluting the ingestion schema. Real ingestion already adds its own IDs; do not
apply the synthetic adapter to real exported data.

```python
import json
from pathlib import Path
from clustering.evaluation.generate_timeline import as_stored_logs
from clustering.src.pipeline import analyze

run = Path('/tmp/issue98-seed98')
logs = as_stored_logs(json.loads((run / 'logs.json').read_text()))
records = analyze(logs, '2026-01-01T00:41:00Z',
                  window_seconds=60, history_windows=30, threshold=2.0)
```

The existing CLI accepts the labels, including aliases:

```sh
python -B -m clustering.evaluation.precision_recall \
  --predictions /path/to/predictions.json --labels /tmp/issue98-seed98/labels.json
```

Matching still checks service-derived cluster ID, normalized signature and time
overlap. Original one-to-one matching/status filters remain unchanged. Multiple
anomalous window records are not automatically deduplicated: 03b must state its
alert/event aggregation and cooldown policy before interpreting precision,
false alerts/hour or detection delay. Aliases are not inferred from predictions.
Replay requires the full preceding 30 windows of baseline.

## Tests and handoff boundary

```sh
python -m pip install -r clustering/requirements-dev.txt
python -m pytest clustering/tests -q
```

Tests cover byte-identical CLI outputs across processes, seeds, schema, schedule,
cold starts, repeated bursts, quiet intervals, rate/input errors, no overwrite,
replay IDs, aliases and unchanged legacy metrics. CI already discovers the dev
requirements; no workflow change is needed.

The committed issue98 run contains reproducibility/schema checks and a rule-only
input smoke replay. It is not the 32-configuration benchmark. Remaining 03b for
Nam: fresh ML state per combination; replay 60s/30 windows; 4 anomaly thresholds
x 4 ML similarities x ML on/off; all four metrics; benchmark conclusions and
coordinated config changes. Keep the PR Draft and use `Refs #98` until both parts
are complete.
