"""Fixed-window clustering pipeline, independent of storage and webhook delivery."""
from datetime import timedelta
import math

from .clustering import group_similar_errors
from .anomaly_score import _parse_ts, baseline_from_history, compute_anomaly_score


def analyze(logs, window_to, *, window_seconds=60, history_windows=30, threshold=2.0,
            augmenter=None):
    """Use [end-window, end); baseline contains preceding equal windows including zeros.

    Input must cover the full baseline interval. Missing history is treated as zero;
    callers must avoid running against a partially populated ingestion store.
    """
    if window_seconds <= 0 or history_windows < 1 or not math.isfinite(threshold) or threshold < 0:
        raise ValueError("Invalid window, history or threshold")
    end = _parse_ts(window_to)
    start = end - timedelta(seconds=window_seconds)
    history_start = start - timedelta(seconds=window_seconds * history_windows)
    unique = {}
    for log in logs:
        if not log.get("log_id"):
            raise ValueError("Every stored log must have log_id")
        unique.setdefault(log["log_id"], log)
    current, historical = [], []
    for log in unique.values():
        timestamp = _parse_ts(log["timestamp"])
        if start <= timestamp < end:
            current.append(log)
        elif history_start <= timestamp < start:
            historical.append(log)
    history = group_similar_errors(historical)
    current_groups = group_similar_errors(current)
    if augmenter is not None:
        combined = {key: list(items) for key, items in history.items()}
        for key, items in current_groups.items():
            combined.setdefault(key, []).extend(items)
        mapping = augmenter.map_groups(combined)

        def remap(groups):
            merged = {}
            for key, items in groups.items():
                merged.setdefault(mapping[key], []).extend(items)
            return merged

        history, current_groups = remap(history), remap(current_groups)
    result = []
    for key, items in current_groups.items():
        service, signature = key
        counts = [0] * history_windows
        for log in history.get(key, []):
            bucket = int((_parse_ts(log["timestamp"]) - history_start).total_seconds() // window_seconds)
            counts[bucket] += 1
        mean, std = baseline_from_history(counts)
        record = compute_anomaly_score(signature, items, mean, baseline_std=std)
        record["status"] = "anomalous" if record["score"] > threshold else "normal"
        result.append((service, record))
    return result
