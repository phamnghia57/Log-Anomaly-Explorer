"""Seeded synthetic input for issue #98 (03a); no live services or detector calls."""
import argparse
import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from clustering.src.clustering import normalize_message

DEFAULT_START = "2026-01-01T00:00:00Z"
DURATION_MINUTES = 180
WARMUP_MINUTES = 30
SERVICES = ("demo-web", "demo-mobile-api")
FAULTS = {
    "value": (422, "value", "ValidationError", ("invalid item value", "item validation rejected")),
    "connection": (502, "connection", "ConnectError", ("downstream dependency unreachable", "cannot reach downstream dependency")),
    "runtime": (500, "runtime", "RuntimeError", ("runtime operation failed", "application runtime failure")),
    "timeout": (504, "runtime", "TimeoutError", ("downstream request timed out", "downstream timeout exceeded")),
    "downstream": (500, "runtime", "RuntimeError", ("downstream processing failed", "remote processing failure")),
}
HOSTS = ("cache-a.internal", "cache-b.internal", "worker-c.internal")
NOVEL = {
    "new-connection": ("connection", "ShippingGatewayError", ("new shipping gateway unreachable", "new shipping gateway refused connection")),
    "new-value": ("value", "InventoryValidationError", ("new inventory item rejected", "new inventory validation failed")),
}
# start minute, service, family, shape, extra errors per successive minute.
SCENARIOS = (
    (40, "demo-web", "value", "step", (8,) * 5),
    (50, "demo-mobile-api", "connection", "step", (8,) * 5),
    (65, "demo-web", "timeout", "ramp", (2, 4, 6, 8, 10)),
    (80, "demo-mobile-api", "runtime", "ramp", (2, 4, 6, 8, 10)),
    (95, "demo-web", "downstream", "spike", (12,)),
    (105, "demo-web", "new-connection", "new_cluster", (8,) * 4),
    (115, "demo-mobile-api", "new-value", "new_cluster", (8,) * 4),
    (130, "demo-web", "runtime", "repeated_burst", (8,) * 3),
    (137, "demo-web", "runtime", "repeated_burst", (8,) * 3),
    (160, "demo-mobile-api", "timeout", "spike", (12,)),
)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_start(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("start must include a timezone")
    result = result.astimezone(timezone.utc)
    if result.second or result.microsecond:
        raise ValueError("start must align to a 60-second window")
    return result


def _rng(seed, stream):
    # Never use Python's process-randomized hash() for persistent seeds.
    digest = hashlib.sha256(f"{seed}:{stream}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _family(family):
    if family in NOVEL:
        fault, exception, descriptions = NOVEL[family]
        return fault, FAULTS[fault][0], FAULTS[fault][1], exception, descriptions
    status, error_type, exception, descriptions = FAULTS[family]
    return family, status, error_type, exception, descriptions


def _message(family, variant, order, latency, request):
    _, status, _, exception, descriptions = _family(family)
    description = descriptions[(variant // len(HOSTS)) % len(descriptions)]
    host = HOSTS[variant % len(HOSTS)]
    return (f"{exception}: {description}; order {order}; host {host}; "
            f"status {status}; latency {latency} ms; request {request}")


def family_signatures(family):
    """Declared family aliases, independent of predictions and learned ML state."""
    return sorted({normalize_message(_message(family, i, 1, 1, str(UUID(int=0))))
                   for i in range(len(HOSTS) * 2)})


def generate_timeline(*, seed=98, start=DEFAULT_START, background_rate=1.0, fault_rates=None):
    begin = parse_start(start)
    end = begin + timedelta(minutes=DURATION_MINUTES)
    evaluation_from = begin + timedelta(minutes=WARMUP_MINUTES)
    rates = dict.fromkeys(FAULTS, background_rate)
    overrides = fault_rates or {}
    if set(overrides) - FAULTS.keys():
        raise ValueError("unknown fault rate override")
    rates.update(overrides)
    if any(not math.isfinite(rate) or rate < 0 for rate in [background_rate, *rates.values()]):
        raise ValueError("background rates must be finite and nonnegative")
    values = _rng(seed, "values")
    logs, incidents = [], []
    variants = {}

    def emit(service, family, timestamp):
        _, status, error_type, _, _ = _family(family)
        key = (service, family)
        variant = variants.get(key, 0)
        variants[key] = variant + 1
        serial = len(logs) + 1
        digest = hashlib.sha256(f"issue98:{seed}:{serial}".encode()).hexdigest()
        logs.append({
            "timestamp": iso(timestamp), "level": "ERROR", "service": service,
            "trace_id": digest[:32], "span_id": digest[32:48],
            "message": _message(family, variant, values.randint(1, 100_000_000),
                                values.randint(10, 9000), str(UUID(int=values.getrandbits(128), version=4))),
            "metadata": {"synthetic": True, "platform": service.removeprefix("demo-"),
                         "error_type": error_type, "http.status_code": status},
        })

    for service in SERVICES:
        for fault, rate in rates.items():
            arrivals = _rng(seed, f"background:{service}:{fault}")
            elapsed = 0.0
            while rate > 0:
                elapsed += arrivals.expovariate(rate / 60)
                if elapsed >= DURATION_MINUTES * 60:
                    break
                timestamp = begin + timedelta(seconds=elapsed)
                # datetime rounds to microseconds; keep the end boundary exclusive.
                if timestamp < end:
                    emit(service, fault, timestamp)

    for number, (minute, service, family, shape, counts) in enumerate(SCENARIOS, 1):
        window_from = begin + timedelta(minutes=minute)
        window_to = window_from + timedelta(minutes=len(counts))
        aliases = family_signatures(family)
        incidents.append({
            "incident_id": f"synthetic-{number:02d}", "service": service,
            "fault": _family(family)[0], "family": family, "shape": shape,
            "window_from": iso(window_from), "window_to": iso(window_to),
            "expected_cluster_signature": aliases[0], "expected_cluster_signatures": aliases,
            "injected_log_count": sum(counts),
        })
        arrivals = _rng(seed, f"incident:{number}")
        for offset, count in enumerate(counts):
            for _ in range(count):
                seconds = offset * 60 + arrivals.random() * 60
                minute_end = window_from + timedelta(minutes=offset + 1)
                timestamp = min(window_from + timedelta(seconds=seconds), minute_end - timedelta(microseconds=1))
                emit(service, family, timestamp)

    quiet, cursor = [], evaluation_from
    for incident in incidents:
        left, right = parse_start(incident["window_from"]), parse_start(incident["window_to"])
        if cursor < left:
            quiet.append({"window_from": iso(cursor), "window_to": iso(left)})
        cursor = max(cursor, right)
    if cursor < end:
        quiet.append({"window_from": iso(cursor), "window_to": iso(end)})
    labels = {
        "source": "Synthetic scheduled fault injection, not production incidents or captured Jaeger spans",
        "warmup_from": iso(begin), "warmup_to": iso(evaluation_from),
        "evaluation_from": iso(evaluation_from), "evaluation_to": iso(end),
        "quiet_intervals": quiet, "incidents": incidents,
    }
    logs.sort(key=lambda log: (log["timestamp"], log["service"], log["trace_id"]))
    config = {
        "generator_version": 1, "seed": seed, "start": iso(begin), "end": iso(end),
        "duration_minutes": DURATION_MINUTES, "warmup_minutes": WARMUP_MINUTES,
        "window_seconds": 60, "history_windows": 30, "services": list(SERVICES),
        "background_rates_per_minute_per_service": rates,
        "scenarios": [{"incident_id": event["incident_id"], "service": service, "family": family,
                       "shape": shape, "start_minute": minute, "extra_errors_per_minute": list(counts)}
                      for event, (minute, service, family, shape, counts) in zip(incidents, SCENARIOS)],
        "log_count": len(logs), "injected_log_count": sum(i["injected_log_count"] for i in incidents),
        "quiet_definition": "No incident in any service; warm-up excluded; half-open intervals",
    }
    return logs, labels, config


def as_stored_logs(logs):
    """Copy schema-valid input and add deterministic IDs for pipeline.analyze."""
    trace_ids = [log.get("trace_id") for log in logs]
    if any(not trace_id for trace_id in trace_ids) or len(set(trace_ids)) != len(trace_ids):
        raise ValueError("replay requires nonempty unique synthetic trace IDs")
    return [{**log, "log_id": f"synthetic-{log['trace_id']}"} for log in logs]


def write_dataset(output, logs, labels, config):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    # A JSON array with one record per line keeps generated evidence reviewable.
    log_text = "[\n" + ",\n".join("  " + json.dumps(log, sort_keys=True, ensure_ascii=False)
                                  for log in logs) + "\n]\n"
    (output / "logs.json").write_bytes(log_text.encode("utf-8"))
    for name, value in (("labels.json", labels), ("config.json", config)):
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (output / name).write_bytes(text.encode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=98)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--background-rate", type=float, default=1.0, help="Errors/minute per service/fault")
    parser.add_argument("--fault-rate", action="append", default=[], metavar="FAULT=RATE")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        overrides = {}
        for option in args.fault_rate:
            name, value = option.split("=", 1)
            if name in overrides:
                raise ValueError(f"duplicate rate override: {name}")
            overrides[name] = float(value)
        logs, labels, config = generate_timeline(seed=args.seed, start=args.start,
            background_rate=args.background_rate, fault_rates=overrides)
        write_dataset(args.output, logs, labels, config)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(logs)} synthetic logs and {len(labels['incidents'])} incidents to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
