import pytest

from clustering.src.pipeline import analyze


def log(id, ts, **kwargs):
    return dict(log_id=id, timestamp=f"2026-01-01T00:{ts}", service="web", level="ERROR",
                message="timeout", **kwargs)


def test_half_open_windows_deduplication_and_zero_history_buckets():
    # History [00:00, 00:02), current [00:02, 00:03).
    old = log("old", "00:00Z")
    current = log("new", "02:00Z")
    result = analyze([old, current, current, log("end", "03:00Z"),
                      dict(old, log_id="outside", timestamp="2025-12-31T23:59:59Z")],
                     "2026-01-01T00:03:00Z", history_windows=2, threshold=.5)
    service, record = result[0]
    assert service == "web"
    assert record["log_ids"] == ["new"]
    assert record["score"] == .5  # baseline [1, 0], min_std 1
    assert record["status"] == "normal"  # equality does not trigger
    assert analyze([], "2026-01-01T00:03:00Z") == []


def test_new_cluster_and_service_isolation():
    result = analyze([log("a", "02:00Z"), dict(log("b", "01:00Z"), service="api")],
                     "2026-01-01T00:03:00Z", threshold=0)
    assert len(result) == 1
    assert result[0][1]["score"] == 1
    assert result[0][1]["status"] == "anomalous"


def test_augmenter_merges_current_and_historical_groups():
    class Augmenter:
        def map_groups(self, groups):
            assert set(groups) == {("web", "timeout"), ("web", "timed out")}
            return {key: ("web", "timeout") for key in groups}
    records = analyze([log("a", "01:00Z"), dict(log("b", "02:00Z"), message="timed out")],
                      "2026-01-01T00:03:00Z", history_windows=1, augmenter=Augmenter())
    assert len(records) == 1
    assert records[0][1]["signature"] == "timeout"
    assert records[0][1]["score"] == 0


@pytest.mark.parametrize("kwargs", [{"window_seconds": 0}, {"history_windows": 0},
    {"threshold": -1}, {"threshold": float("nan")}, {"threshold": float("inf")}])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        analyze([], "2026-01-01T00:03:00Z", **kwargs)


def test_missing_log_id_rejected():
    with pytest.raises(ValueError, match="log_id"):
        analyze([dict(log("a", "02:00Z"), log_id="")], "2026-01-01T00:03:00Z")
