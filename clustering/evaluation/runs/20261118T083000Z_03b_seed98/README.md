# Issue #98: 03b replay evidence

Synthetic seed 98; 60-second windows, 30-window baseline, 30-minute warm-up,
150 evaluation windows. See `replay_config.json` for metric definitions and
limitations, and `sweep.csv` for all 32 parameter combinations. Predictions
are detector records with threshold 0; each `*-alerts.json` records the alerts
after applying the indicated threshold and simulated 600-second cooldown.
ML-off similarity rows reuse identical results because similarity is inactive.
Scores are independent of anomaly threshold, so each ML policy is replayed once
and thresholding is applied afterwards; fresh ML state is used for each policy.

Run from the repository root in an environment with `clustering/requirements-ml.txt`:

```sh
python -m clustering.evaluation.sweep --seed 98 --output /tmp/issue98-03b-new
python -m clustering.evaluation.generate_timeline --seed 98 --output /tmp/issue98-03a-new
```

The generator CLI was rerun separately: `logs.json`, `labels.json` and
`config.json` have identical SHA-256 hashes to this run and the committed 03a
dataset (respectively `59a559e30c272064c2e19e98ebc07b2ddcdfc9375810e2253393efee7cf1aff8`,
`98a8c8646ebd549a24360c378b518dcd4b5518d8a8740c1479afccda90bcc1e2`,
`a8a8ca2ddfb19684aced9decedff25591b95db72dd8360b915d82fd3c686a91b`).
This is offline simulation, not proof of live webhook delivery or production quality.
