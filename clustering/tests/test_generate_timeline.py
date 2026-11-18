import copy
import json
import random
import re
import subprocess
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker

from clustering.evaluation.generate_timeline import (
    as_stored_logs, generate_timeline, main, parse_start, write_dataset,
)
from clustering.src.clustering import normalize_message
from clustering.src.pipeline import analyze

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dataset():
    return generate_timeline()


def test_all_logs_match_real_schema_without_ground_truth_or_storage_fields(dataset):
    logs, labels, config = dataset
    schema = json.loads((ROOT / "docs/architect/contracts/log-schema.json").read_text())
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    assert logs
    for log in logs:
        validator.validate(log)
        assert re.fullmatch(r"[0-9a-f]{32}", log["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", log["span_id"])
        assert set(log["metadata"]) == {"synthetic", "platform", "error_type", "http.status_code"}
        assert config["start"] <= log["timestamp"] < config["end"]
    assert len({row["trace_id"] for row in logs}) == len(logs)
    assert len({row["span_id"] for row in logs}) == len(logs)
    assert logs == sorted(logs, key=lambda row: (row["timestamp"], row["service"], row["trace_id"]))
    assert {row["service"] for row in logs} == {"demo-web", "demo-mobile-api"}
    assert len(labels["incidents"]) == 10


def test_seeded_files_are_byte_identical_across_cli_processes_and_directories(tmp_path):
    random.seed(123)
    state = random.getstate()
    first = generate_timeline(seed=98)
    assert random.getstate() == state
    write_dataset(tmp_path / "first", *first)
    command = [sys.executable, "-B", "-m", "clustering.evaluation.generate_timeline", "--seed", "98",
               "--output", str(tmp_path / "second")]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    for name in ("logs.json", "labels.json", "config.json"):
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()
    changed = generate_timeline(seed=99)
    assert changed[0] != first[0]
    # The incident schedule/ground truth is not chosen to fit a detector or seed.
    assert changed[1] == first[1]


def test_scenarios_shapes_novelty_and_automatic_aliases():
    # With zero background, per-window counts are exactly the injected shapes.
    logs, labels, config = generate_timeline(background_rate=0)
    assert len(logs) == config["injected_log_count"] == 276
    assert {event["fault"] for event in labels["incidents"]} == {
        "value", "connection", "runtime", "timeout", "downstream"}
    assert {event["shape"] for event in labels["incidents"]} == {
        "step", "ramp", "spike", "new_cluster", "repeated_burst"}
    assert all(log["timestamp"] >= labels["warmup_to"] for log in logs)
    for event, scenario in zip(labels["incidents"], config["scenarios"]):
        aliases = set(event["expected_cluster_signatures"])
        matching = [row for row in logs if row["service"] == event["service"]
                    and normalize_message(row["message"]) in aliases
                    and event["window_from"] <= row["timestamp"] < event["window_to"]]
        begin = parse_start(event["window_from"])
        buckets = Counter(int((parse_timestamp(row["timestamp"]) - begin).total_seconds() // 60)
                          for row in matching)
        assert [buckets[i] for i in range(len(scenario["extra_errors_per_minute"]))] == scenario["extra_errors_per_minute"]
        assert event["injected_log_count"] == len(matching)
        assert len({normalize_message(row["message"]) for row in matching}) > 1
        if event["shape"] == "new_cluster":
            assert not any(row["service"] == event["service"]
                           and row["timestamp"] < event["window_from"]
                           and normalize_message(row["message"]) in aliases for row in logs)
    repeats = [event for event in labels["incidents"] if event["shape"] == "repeated_burst"]
    assert repeats[0]["service"] == repeats[1]["service"]
    assert repeats[0]["expected_cluster_signatures"] == repeats[1]["expected_cluster_signatures"]
    assert parse_start(repeats[1]["window_from"]) - parse_start(repeats[0]["window_to"]) == timedelta(minutes=4)


def parse_timestamp(value):
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_quiet_intervals_partition_evaluation_and_exclude_warmup(dataset):
    _, labels, _ = dataset
    intervals = [(parse_start(i["window_from"]), parse_start(i["window_to"]))
                 for i in labels["quiet_intervals"] + labels["incidents"]]
    cursor = parse_start(labels["evaluation_from"])
    for start, end in sorted(intervals):
        assert start == cursor
        assert end > start
        cursor = end
    assert cursor == parse_start(labels["evaluation_to"])
    quiet_seconds = sum((parse_start(i["window_to"]) - parse_start(i["window_from"])).total_seconds()
                        for i in labels["quiet_intervals"])
    assert quiet_seconds == 114 * 60


def test_background_is_variable_and_fault_override_is_respected(dataset):
    logs, labels, _ = dataset
    warm = [row for row in logs if row["timestamp"] < labels["warmup_to"]]
    assert len(warm) > 0
    assert {row["metadata"]["http.status_code"] for row in warm} == {422, 500, 502, 504}
    counts = Counter(row["timestamp"][:16] for row in warm)
    assert len(set(counts.values())) > 1
    no_timeout, labels, config = generate_timeline(fault_rates={"timeout": 0})
    assert config["background_rates_per_minute_per_service"]["timeout"] == 0
    assert not any(row["metadata"]["http.status_code"] == 504
                   for row in no_timeout if row["timestamp"] < labels["warmup_to"])


def test_replay_adapter_does_not_mutate_schema_valid_logs_and_pipeline_runs(dataset):
    logs, labels, _ = dataset
    original = copy.deepcopy(logs)
    stored = as_stored_logs(logs)
    assert logs == original
    assert stored == as_stored_logs(logs)
    assert len({row["log_id"] for row in stored}) == len(logs)
    records = analyze(stored, labels["incidents"][0]["window_to"],
                      window_seconds=60, history_windows=30)
    assert records
    assert all(record["log_ids"] for _, record in records)
    with pytest.raises(ValueError):
        as_stored_logs([logs[0], logs[0]])


@pytest.mark.parametrize("rate", [-1, float("nan"), float("inf"), -float("inf")])
def test_invalid_rates(rate):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        generate_timeline(background_rate=rate)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        generate_timeline(fault_rates={"runtime": rate})


@pytest.mark.parametrize("start", ["invalid", "2026-01-01T00:00:00", "2026-01-01T00:00:01Z"])
def test_invalid_start(start):
    with pytest.raises(ValueError):
        generate_timeline(start=start)


def test_timezone_equivalence_and_invalid_cli_does_not_write(tmp_path):
    assert generate_timeline(start="2026-01-01T07:00:00+07:00") == generate_timeline()
    for rates in ({"bad_schema": 1}, {"unknown": 0}):
        with pytest.raises(ValueError):
            generate_timeline(fault_rates=rates)
    output = tmp_path / "invalid"
    with pytest.raises(SystemExit) as exc:
        main(["--fault-rate", "value=1", "--fault-rate", "value=2", "--output", str(output)])
    assert exc.value.code == 2
    assert not output.exists()


def test_existing_output_is_not_modified(tmp_path, dataset):
    output = tmp_path / "protected"
    write_dataset(output, *dataset)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(FileExistsError):
        write_dataset(output, *generate_timeline(seed=1))
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_submicrosecond_rounding_keeps_injections_in_the_assigned_minute(monkeypatch):
    from clustering.evaluation import generate_timeline as generator
    original = generator._rng

    class NearBoundary:
        def random(self):
            return .9999999999

    monkeypatch.setattr(generator, "_rng", lambda seed, stream:
                        NearBoundary() if stream.startswith("incident:") else original(seed, stream))
    logs, _, _ = generator.generate_timeline(background_rate=0)
    step = [row for row in logs if row["service"] == "demo-web"
            and row["metadata"]["http.status_code"] == 422
            and "2026-01-01T00:40" <= row["timestamp"] < "2026-01-01T00:45"]
    assert sorted(Counter(row["timestamp"][:16] for row in step).values()) == [8] * 5


@pytest.mark.parametrize("options", [
    ["--background-rate", "-1"], ["--background-rate", "nan"],
    ["--fault-rate", "timeout=inf"], ["--fault-rate", "bad_schema=1"],
    ["--fault-rate", "value=invalid"], ["--start", "2026-01-01T00:00:00"],
])
def test_invalid_cli_input_fails_before_creating_output(tmp_path, options):
    output = tmp_path / "invalid"
    with pytest.raises(SystemExit) as exc:
        main([*options, "--output", str(output)])
    assert exc.value.code == 2
    assert not output.exists()
