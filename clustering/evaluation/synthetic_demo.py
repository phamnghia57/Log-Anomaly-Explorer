"""Deterministic synthetic evidence; never presented as real fault injection."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline import analyze
from precision_recall import evaluate


def sample_logs():
    logs = []
    for minute, count in [(0, 2), (1, 2), (2, 8)]:
        for i in range(count):
            logs.append({"log_id": f"{minute}-{i}", "timestamp": f"2026-10-01T09:0{minute}:10Z",
                         "level": "ERROR", "service": "demo-web", "trace_id": f"trace-{minute}-{i}",
                         "span_id": f"span-{i}", "message": f"Payment timeout for order {100 + i}"})
    logs.append({**logs[-1], "log_id": "normal", "message": "User 42 not found"})
    return logs


if __name__ == "__main__":
    root = Path(__file__).parent
    predictions = [record for _, record in analyze(sample_logs(), "2026-10-01T09:03:00Z", history_windows=2)]
    (root / "synthetic_predictions.json").write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    print(json.dumps(evaluate(predictions, root / "synthetic_incidents.json"), indent=2))
