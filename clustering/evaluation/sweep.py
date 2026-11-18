"""Replay the seeded 03a timeline using the production detector, without webhooks."""
import argparse
import csv
import json
import logging
import platform
import sys
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from clustering.evaluation.generate_timeline import as_stored_logs, generate_timeline, write_dataset
from clustering.evaluation.precision_recall import _cluster_overlaps_incident, timestamp
from clustering.src.ml_augment import TfidfAugmenter
from clustering.src.pipeline import analyze

THRESHOLDS = (1.5, 2.0, 3.0, 4.0)
SIMILARITIES = (0.8, 0.85, 0.9, 0.95)
COOLDOWN = 600


def measure(records, labels, threshold):
    """Simulate successful delivery with per-cluster 600s cooldown, no acknowledgements."""
    incidents = labels["incidents"]
    quiet = [(timestamp(x["window_from"]), timestamp(x["window_to"])) for x in labels["quiet_intervals"]]
    quiet_hours = sum((end - start).total_seconds() for start, end in quiet) / 3600
    last_sent, detections, alerts = {}, {}, []
    for end, cluster in records:
        end = timestamp(end)
        if cluster["score"] <= threshold:
            continue
        previous = last_sent.get(cluster["cluster_id"])
        if previous is not None and (end - previous).total_seconds() < COOLDOWN:
            continue
        last_sent[cluster["cluster_id"]] = end
        matched = [incident for incident in incidents if _cluster_overlaps_incident(cluster, incident)]
        for incident in matched:
            detections.setdefault(incident["incident_id"], (end - timestamp(incident["window_from"])).total_seconds() / 60)
        window_start = end - timedelta(seconds=60)
        is_quiet = any(start <= window_start and end <= stop for start, stop in quiet)
        alerts.append({"window_to": end.isoformat(), "cluster": cluster,
                       "matched_incidents": [i["incident_id"] for i in matched], "quiet": is_quiet})
    true_alerts = sum(bool(a["matched_incidents"]) for a in alerts)
    false_quiet = sum(a["quiet"] and not a["matched_incidents"] for a in alerts)
    return {"precision": true_alerts / len(alerts) if alerts else 0.0,
            "recall": len(detections) / len(incidents) if incidents else 0.0,
            "false_alerts_per_hour": false_quiet / quiet_hours,
            "mean_detection_delay_windows": sum(detections.values()) / len(detections) if detections else None,
            "alert_count": len(alerts), "true_alert_count": true_alerts,
            "detected_incidents": len(detections), "quiet_false_alerts": false_quiet}, alerts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=98)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import sklearn

    class FailOnMLFallback(logging.Handler):
        def emit(self, record):
            raise RuntimeError("ML augmentation failed; refusing invalid benchmark")

    logging.getLogger("clustering.src.ml_augment").addHandler(FailOnMLFallback())
    logs, labels, config = generate_timeline(seed=args.seed)
    write_dataset(args.output, logs, labels, config)
    stored = as_stored_logs(logs)
    start, evaluation, end = map(timestamp, (config["start"], labels["evaluation_from"], config["end"]))
    predictions_dir = args.output / "predictions"
    predictions_dir.mkdir()
    rows = []
    with TemporaryDirectory() as tmp:
        # Scores and mapping are independent of anomaly threshold; replay once per ML policy.
        for enabled, similarity in [(False, 0.9)] + [(True, x) for x in SIMILARITIES]:
            name = f"ml-{similarity}" if enabled else "rule"
            augmenter = TfidfAugmenter(Path(tmp) / f"{name}.json", threshold=similarity) if enabled else None
            records = []
            cursor = start + timedelta(seconds=60)
            while cursor <= end:
                result = analyze(stored, cursor.isoformat(), window_seconds=60, history_windows=30,
                                 threshold=0, augmenter=augmenter)
                if cursor > evaluation:
                    records.extend((cursor.isoformat(), record) for _, record in result)
                cursor += timedelta(seconds=60)
            (predictions_dir / f"{name}.json").write_text(json.dumps(records, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
            for threshold in THRESHOLDS:
                metrics, alerts = measure(records, labels, threshold)
                for candidate in ([similarity] if enabled else SIMILARITIES):
                    rows.append({"anomaly_threshold": threshold, "ml_similarity_threshold": candidate,
                                 "ml_enabled": str(enabled).lower(), **metrics})
                (predictions_dir / f"{name}-threshold-{threshold}-alerts.json").write_text(
                    json.dumps(alerts, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
            print(f"Finished {name}: {len(records)} evaluated records", flush=True)
    rows.sort(key=lambda r: (r["anomaly_threshold"], r["ml_similarity_threshold"], r["ml_enabled"]))
    with (args.output / "sweep.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "replay_config.json").write_text(json.dumps({
        "window_seconds": 60, "history_windows": 30, "cooldown_seconds": COOLDOWN,
        "ml_margin": 0.05, "ml_max_templates": 2000, "warmup_replayed": True,
        "delivery": "simulated successful; no webhook or incident acknowledgement",
        "precision": "fraction of sent cluster alerts matching an incident by service, signature and time overlap; repeated alerts count",
        "recall": "fraction of incidents matched by at least one sent alert",
        "quiet_rate": "unmatched sent alerts in globally quiet windows / quiet hours",
        "delay": "mean completed 60s windows from incident start to first matching sent alert; excludes missed incidents",
        "python": sys.version, "platform": platform.platform(), "scikit_learn": sklearn.__version__,
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(rows)} configurations to {args.output}", flush=True)


if __name__ == "__main__":
    main()
