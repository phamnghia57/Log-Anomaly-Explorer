"""
Tinh Anomaly Score cho tung cum loi.

TODO (Nam): thay placeholder (so sanh dem don gian) bang so sanh
voi baseline tan suat lich su that (vd. trung binh truot / do lech chuan
theo khung gio, hoac mo hinh thong ke phuc tap hon).
"""

from __future__ import annotations

import math
import statistics

from datetime import datetime, timezone
from .clustering import make_cluster_id

def baseline_from_history(counts: list[int]) -> tuple[float, float]:
    """Tinh (mean, std) tu so loi cua cum o cac cua so truoc do.

    `counts` phai gom ca cac cua so co 0 loi (cum khong xuat hien), neu khong
    baseline se bi cao hon thuc te. Chua co lich su -> (0.0, 0.0).
    """
    if any(not math.isfinite(count) or count < 0 for count in counts):
        raise ValueError("History counts must be finite and nonnegative")
    if not counts:
        return 0.0, 0.0
    mean = statistics.fmean(counts)
    std = statistics.stdev(counts) if len(counts) > 1 else 0.0
    return mean, std

def _parse_ts(value: str) -> datetime:
    """Parse ISO 8601 (chap nhan hau to Z hoac +00:00). Thieu mui gio -> coi la UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

def compute_anomaly_score(
    signature: str,
    logs: list[dict],
    baseline_rate: float,
    *,
    baseline_std: float = 0.0,
    min_std: float = 1.0,
) -> dict:
    """Tra ve mot ClusterRecord (dung theo docs/architect/contracts/cluster-record.schema.json).

    `baseline_rate`: tan suat binh thuong (so loi/khoang thoi gian) cho signature nay,
    lay tu lich su. Placeholder o day chi tinh ty le giua so luong thuc te va baseline.
    """
    if not logs or any(not math.isfinite(v) or v < 0 for v in (baseline_rate, baseline_std)) or not math.isfinite(min_std) or min_std <= 0:
        raise ValueError("Nonempty logs, finite nonnegative baseline and positive min_std required")
    if len({log.get("service", "unknown") for log in logs}) != 1:
        raise ValueError("A cluster cannot contain multiple services")
    count = len(logs)
    effective_std = max(baseline_std, math.sqrt(max(baseline_rate, 0.0)), min_std)
    score = max(0.0, (count - baseline_rate) / effective_std)

    service = next((log["service"] for log in logs if log.get("service")), "unknown")

    # Sort theo thoi gian that (khong sort chuoi): log co the dung "Z" hoac "+00:00".
    stamped = sorted(
        ((_parse_ts(log["timestamp"]), log["timestamp"]) for log in logs if log.get("timestamp")),
        key=lambda pair: pair[0],
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "cluster_id": make_cluster_id(service, signature),
        "signature": signature,
        "score": score,
        "log_ids": [log["log_id"] for log in logs if log.get("log_id")],
        "trace_ids": sorted({log["trace_id"] for log in logs if log.get("trace_id")}),
        "first_seen": stamped[0][1] if stamped else now_iso,
        "last_seen": stamped[-1][1] if stamped else now_iso,
        "status": "normal",
    }
