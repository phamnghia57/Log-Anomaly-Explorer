# Issue #98 — 03a synthetic evidence

Validation time (UTC): 2026-11-17T20:29:35.568498+00:00. Python 3.11.18.
Base: `b083a3ead2ee620c5df5e05f5dfa2d9bcf2dbcce`; generator/evaluator changes are in this PR.

- Seed 98; fixed synthetic timeline 2026-01-01 00:00–03:00 UTC.
- 2070 schema-valid logs: 1794 Poisson background + 276 injected.
- 10 labeled incidents; 30 minutes warm-up; 150 evaluated minutes; 114 quiet minutes.
- Two separate CLI processes/output paths produced byte-identical logs, labels and config.
- All 100 clustering tests passed, including legacy metrics regression and alias contracts.
- Rule-only input smoke replay: 150 windows, 1686 schema-valid records,
  window 60s, history 30, threshold 2.0. This is a compatibility check, not the final benchmark.

## SHA-256

- `logs.json`: `59a559e30c272064c2e19e98ebc07b2ddcdfc9375810e2253393efee7cf1aff8`
- `labels.json`: `98a8c8646ebd549a24360c378b518dcd4b5518d8a8740c1479afccda90bcc1e2`
- `config.json`: `a8a8ca2ddfb19684aced9decedff25591b95db72dd8360b915d82fd3c686a91b`

## Reproduce

From the repository root, using a new output directory:

```sh
python -B -m clustering.evaluation.generate_timeline --seed 98 --output /tmp/issue98-reproduce
python -m pytest clustering/tests -q
```

Compare the three dataset hashes above. `validation.json`, this README and test
timings describe the actual validation run and are not deterministic dataset output.
See [the generator/handoff contract](../../README.md) for rate overrides, alias
matching, replay IDs and quiet-period definitions. No Docker or external services
were used, and no deployed settings or shared volumes were changed.

## Pending for Nam (03b)

32-combination replay/sweep, fresh ML state per combination, four metrics,
alert/event aggregation policy, benchmark conclusions and any agreed config updates.
No precision/recall, false-alert rate, delay or best threshold is claimed here.
Synthetic trace IDs are not captured Jaeger spans. Historical live evidence stays intact.
