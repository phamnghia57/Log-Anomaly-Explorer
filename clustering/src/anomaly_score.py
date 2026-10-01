"""
Tinh Anomaly Score cho tung cum loi.

TODO (Nam): thay placeholder (so sanh dem don gian) bang so sanh
voi baseline tan suat lich su that (vd. trung binh truot / do lech chuan
theo khung gio, hoac mo hinh thong ke phuc tap hon).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def compute_anomaly_score(signature: str, logs: list[dict], baseline_rate: float) -> dict:
    """Tra ve mot ClusterRecord (dung theo docs/contracts/cluster-record.schema.json).

    `baseline_rate`: tan suat binh thuong (so loi/khoang thoi gian) cho signature nay,
    lay tu lich su. Placeholder o day chi tinh ty le giua so luong thuc te va baseline.
    """
    count = len(logs)
    score = 0.0 if baseline_rate <= 0 else max(0.0, (count - baseline_rate) / baseline_rate)

    timestamps = sorted(log["timestamp"] for log in logs)
    return {
        "cluster_id": str(uuid.uuid4()),
        "signature": signature,
        "score": round(score, 3),
        "log_ids": [log.get("log_id", "") for log in logs],
        "trace_ids": sorted({log["trace_id"] for log in logs if log.get("trace_id")}),
        "first_seen": timestamps[0] if timestamps else datetime.now(timezone.utc).isoformat(),
        "last_seen": timestamps[-1] if timestamps else datetime.now(timezone.utc).isoformat(),
        "status": "normal",
    }
