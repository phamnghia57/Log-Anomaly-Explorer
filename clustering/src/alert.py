"""
Alert dispatcher.

TODO (Nam): cau hinh ANOMALY_THRESHOLD va ALERT_WEBHOOK_URL that,
va goi check_and_alert() sau moi lan compute_anomaly_score().
"""

from __future__ import annotations

import math
import logging
import os
import time

import httpx

logger = logging.getLogger("clustering.alert")

DEFAULT_THRESHOLD = 2.0
DEFAULT_COOLDOWN_SECONDS = 600.0

# cluster_id -> thoi diem (monotonic) da gui alert gan nhat. Chi nam trong bo nho:
# khoi dong lai process thi cooldown bat dau lai.
_last_alert: dict[str, float] = {}


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Expected finite nonnegative value")
        return value
    except ValueError:
        logger.warning("%s=%r khong phai so, dung mac dinh %s", name, raw, default)
        return default


def get_threshold() -> float:
    return _float_env("ANOMALY_THRESHOLD", DEFAULT_THRESHOLD)


def get_webhook_url() -> str:
    return os.environ.get("ALERT_WEBHOOK_URL", "").strip()


def reset_alert_state() -> None:
    """Xoa bo nho cooldown (dung trong test)."""
    _last_alert.clear()


def check_and_alert(cluster: dict, service: str = "") -> bool:
    """Neu cluster['score'] > ANOMALY_THRESHOLD: gui alert va cap nhat status.

    Tra ve True neu da gui alert. Payload gui di xem docs/architect/contracts/api-contract.md.
    """
    if cluster["score"] <= get_threshold():
        cluster["status"] = "normal"
        return False

    cluster["status"] = "anomalous"
    cluster_id = cluster["cluster_id"]

    last = _last_alert.get(cluster_id)
    if last is not None and time.monotonic() - last < _float_env(
        "ALERT_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS
    ):
        cluster["status"] = "alerted"  # da bao gan day, khong gui lai
        return False

    webhook = get_webhook_url()
    if not webhook:
        # Chua cau hinh webhook - de lai TODO thay vi fail am tham.
        # Chua cau hinh webhook: giu "anomalous" (chua gui), khong gia vo da gui.
        logger.warning("ALERT_WEBHOOK_URL chua cau hinh - cum %s vuot nguong nhung chua gui alert", cluster_id)
        return False

    payload = {
        "cluster_id": cluster_id,
        "score": cluster["score"],
        "service": service,
        "first_seen": cluster["first_seen"],
    }
    try:
        response = httpx.post(webhook, json=payload, timeout=3.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("gui alert that bai cho cum %s: %s", cluster_id, exc)
        return False  # van "anomalous", lan chay sau se thu lai

    _last_alert[cluster_id] = time.monotonic()
    cluster["status"] = "alerted"
    return True
