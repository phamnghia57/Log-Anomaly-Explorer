"""
Alert dispatcher.

TODO (Nam): cau hinh ANOMALY_THRESHOLD va ALERT_WEBHOOK_URL that,
va goi check_and_alert() sau moi lan compute_anomaly_score().
"""

from __future__ import annotations

import os

import httpx

ANOMALY_THRESHOLD = float(os.environ.get("ANOMALY_THRESHOLD", "2.0"))
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")


def check_and_alert(cluster: dict) -> bool:
    """Neu cluster['score'] > ANOMALY_THRESHOLD: gui alert va cap nhat status.

    Tra ve True neu da gui alert. Payload gui di xem docs/architect/contracts/api-contract.md.
    """
    if cluster["score"] <= ANOMALY_THRESHOLD:
        cluster["status"] = "normal" if cluster["score"] == 0 else "anomalous"
        return False

    cluster["status"] = "alerted"

    if not ALERT_WEBHOOK_URL:
        # Chua cau hinh webhook - de lai TODO thay vi fail am tham.
        return False

    payload = {
        "cluster_id": cluster["cluster_id"],
        "score": cluster["score"],
        "service": cluster.get("service", ""),
        "first_seen": cluster["first_seen"],
    }
    try:
        httpx.post(ALERT_WEBHOOK_URL, json=payload, timeout=3.0)
        return True
    except httpx.HTTPError:
        return False
