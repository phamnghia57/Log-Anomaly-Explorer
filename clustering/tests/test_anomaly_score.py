import math

import pytest

from clustering.src.anomaly_score import baseline_from_history, compute_anomaly_score, _parse_ts
from clustering.src.clustering import make_cluster_id


@pytest.mark.parametrize("counts,expected", [([], (0, 0)), ([3], (3, 0)), ([0, 2, 4], (2, 2))])
def test_baseline_includes_zero_windows(counts, expected):
    assert baseline_from_history(counts) == expected


@pytest.mark.parametrize("value", [-1, math.nan, math.inf])
def test_invalid_history(value):
    with pytest.raises(ValueError):
        baseline_from_history([value])


def logs():
    return [dict(service="web", log_id="a", trace_id="z", timestamp="2026-01-01T08:00:00+07:00"),
            dict(service="web", log_id="b", trace_id="z", timestamp="2026-01-01T00:30:00Z")]


def test_record_preserves_evidence_and_sorts_actual_instants():
    record = compute_anomaly_score("timeout", logs(), 0)
    assert record == dict(cluster_id=make_cluster_id("web", "timeout"), service="web",
                         signature="timeout", score=2, log_ids=["a", "b"], trace_ids=["z"],
                         first_seen=logs()[1]["timestamp"], last_seen=logs()[0]["timestamp"], status="normal")


@pytest.mark.parametrize("rate,std,floor,expected", [(0, 0, 1, 2), (4, 0, 1, 0),
    (1, 4, 1, .25), (1, 0, 2, .5), (.25, 0, .1, 3.5)])
def test_score_uses_positive_deviation_and_largest_denominator(rate, std, floor, expected):
    assert compute_anomaly_score("x", logs(), rate, baseline_std=std, min_std=floor)["score"] == expected


@pytest.mark.parametrize("kwargs", [{"baseline_rate": -1}, {"baseline_rate": math.nan},
    {"baseline_rate": math.inf}, {"baseline_std": -1}, {"baseline_std": math.inf},
    {"min_std": 0}, {"min_std": math.nan}])
def test_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        compute_anomaly_score("x", logs(), **({"baseline_rate": 0} | kwargs))


def test_empty_or_mixed_services_rejected():
    with pytest.raises(ValueError):
        compute_anomaly_score("x", [], 0)
    mixed = logs()
    mixed[0]["service"] = "api"
    with pytest.raises(ValueError):
        compute_anomaly_score("x", mixed, 0)


def test_naive_timestamps_are_utc():
    assert _parse_ts("2026-01-01T00:00:00") == _parse_ts("2026-01-01T00:00:00Z")
