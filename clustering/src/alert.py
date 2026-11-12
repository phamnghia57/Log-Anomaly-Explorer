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

# Compatibility cache for standalone callers. The worker supplies durable storage.
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


def check_and_alert(cluster: dict, service: str = "", *, store=None) -> bool:
    """Compatibility entry point for sending one cluster."""
    return bool(check_and_alert_batch([(service, cluster)], store=store))


def check_and_alert_batch(records, *, window_to=None, store=None) -> int:
    """Send one digest per cycle; only successful delivery starts cooldown."""
    records = list(records)
    threshold = get_threshold()
    cooldown = _float_env("ALERT_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS)
    candidates = list(dict.fromkeys(c["cluster_id"] for _, c in records if c["score"] > threshold))
    # Production uses persistent epoch timestamps; legacy standalone callers use monotonic RAM.
    last_alert = store.get_alert_times(candidates) if store is not None else _last_alert
    clock = time.time if store is not None else time.monotonic
    now = clock()
    pending = []
    for service, cluster in records:
        if cluster["score"] <= threshold:
            cluster["status"] = "normal"
            continue
        cluster["status"] = "anomalous"
        last = last_alert.get(cluster["cluster_id"])
        if last is not None and now - last < cooldown:
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
    sent_at = clock()
    if store is not None:
        store.write_alert_times([c["cluster_id"] for _, c in pending], sent_at)
    for _, cluster in pending:
        if store is None:
            _last_alert[cluster["cluster_id"]] = sent_at
        cluster["status"] = "alerted"
    return len(pending)
