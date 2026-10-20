# Integration ? 2026-10-20

Status: PASSED on retry after Docker Desktop was restored.

Evidence: integration/20261020050649/report.json and adjacent requests, logs, predictions, webhooks and service logs.

- Real demo-app -> HTTP ingestion -> OpenSearch 2.17.1 -> clustering worker -> local HTTP webhook.
- Three faults (value, connection, runtime) on web and mobile: six incident cases.
- Four 30-second windows: baseline 1, baseline 1, spike 6, recovery 1 errors per signature.
- Stored 58 logs (54 ERROR + 4 INFO), all with nonzero OTel trace/span IDs.
- Six spike clusters validated against the shared schema, linked to stored logs/traces, and alerted through six successful HTTP requests.
- Recovery clusters returned to normal without additional webhooks.
- Incident evaluation: TP=6, FP=0, FN=0, precision=1.0, recall=1.0 on this controlled local scenario.
- Known injection parameters determine the labels; team review remains appropriate. No production accuracy claim.
- Python services started for the test were stopped. OpenSearch container and isolated evidence indexes remain.
- Source changes confined to clustering/. No changes staged or committed by the runner.

Earlier attempt: image download failed with unexpected EOF; Docker Engine then returned 500/EOF. That issue was resolved before the successful retry.
