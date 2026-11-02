"""Dispatch alerts using configured thresholds and webhook cooldown."""

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
    """Compatibility entry point for sending one cluster."""
    return bool(check_and_alert_batch([(service, cluster)]))


def check_and_alert_batch(records, *, window_to=None) -> int:
    """Send one digest per cycle; only successful delivery starts cooldown."""
    pending = []
    for service, cluster in records:
        if cluster["score"] <= get_threshold():
            cluster["status"] = "normal"
            continue
        cluster["status"] = "anomalous"
        last = _last_alert.get(cluster["cluster_id"])
        if last is not None and time.monotonic() - last < _float_env(
            "ALERT_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS
        ):
            cluster["status"] = "alerted"
            continue
        pending.append((service, cluster))
    if not pending:
        return 0
    webhook = get_webhook_url()
    if not webhook:
        logger.warning("ALERT_WEBHOOK_URL is missing; %d alerts remain unsent", len(pending))
        return 0
    alerts = [{
        "cluster_id": cluster["cluster_id"], "score": cluster["score"],
        "service": service, "first_seen": cluster["first_seen"],
        "trace_id": next(iter(cluster.get("trace_ids") or []), None),
    } for service, cluster in pending]
    subject = f"Log Anomaly Explorer: {len(alerts)} alerts"
    message = "\n\n".join(
        f"Service: {a['service']}\nCluster: {a['cluster_id']}\nScore: {a['score']}"
        f"\nFirst seen: {a['first_seen']}\nTrace: {a['trace_id'] or '-'}"
        for a in alerts
    )
    # Keep legacy fields for existing consumers; digest consumers use alerts/message.
    payload = {**alerts[0], "alerts": alerts, "count": len(alerts),
               "window_to": window_to, "subject": subject, "message": message}
    try:
        response = httpx.post(webhook, json=payload, timeout=3.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Alert digest failed: %s", exc)
        return 0
    sent_at = time.monotonic()
    for _, cluster in pending:
        _last_alert[cluster["cluster_id"]] = sent_at
        cluster["status"] = "alerted"
    return len(pending)
