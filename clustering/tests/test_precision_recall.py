import json
from pathlib import Path

import pytest

from clustering.evaluation.precision_recall import _cluster_overlaps_incident, evaluate
from clustering.src.clustering import make_cluster_id, normalize_message

START = "2026-01-01T00:40:00Z"
END = "2026-01-01T00:45:00Z"


def incident(**changes):
    return {"incident_id": "one", "service": "demo-web", "window_from": START, "window_to": END,
            "expected_cluster_signature": "Timeout for order 123", **changes}


def prediction(message="Timeout for order 456", service="demo-web", **changes):
    signature = normalize_message(message)
    return {"service": service, "signature": signature,
            "cluster_id": make_cluster_id(service, signature), "status": "anomalous",
            "first_seen": START, "last_seen": START, **changes}


def test_legacy_signature_and_normalization_unchanged():
    assert _cluster_overlaps_incident(prediction(), incident())
    assert not _cluster_overlaps_incident(prediction(service="demo-mobile-api"), incident())
    assert not _cluster_overlaps_incident(prediction(cluster_id="wrong"), incident())


def test_aliases_match_other_declared_variants_not_other_faults():
    label = incident(expected_cluster_signatures=["Timeout for order 123", "Payment timeout on cache-b.internal"])
    assert _cluster_overlaps_incident(prediction("Payment timeout on cache-b.internal"), label)
    assert not _cluster_overlaps_incident(prediction("Payment rejected on cache-b.internal"), label)
    assert not _cluster_overlaps_incident(prediction("Payment timeout on cache-b.internal", service="demo-mobile-api"), label)
    assert not _cluster_overlaps_incident(prediction(first_seen=END, last_seen=END), label)
    assert _cluster_overlaps_incident(prediction(first_seen=START, last_seen=START), label)


@pytest.mark.parametrize("aliases", [[], "timeout", [""], ["   "], [None], [1]])
def test_invalid_aliases_rejected(aliases):
    with pytest.raises(ValueError, match="Expected signatures"):
        _cluster_overlaps_incident(prediction(), incident(expected_cluster_signatures=aliases))


def test_one_to_one_matching_and_status_filter_are_preserved(tmp_path):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"incidents": [incident()]}))
    result = evaluate([prediction(), prediction(), prediction(status="normal")], labels)
    assert result == {"precision": .5, "recall": 1.0, "true_positive": 1,
                      "false_positive": 1, "false_negative": 0}


@pytest.mark.parametrize("mode", ["rule", "ml"])
def test_published_legacy_evidence_keeps_its_original_metrics(mode):
    run = Path(__file__).resolve().parents[1] / "evaluation/runs/20261023T164049Z"
    result = evaluate(json.loads((run / f"predictions-{mode}.json").read_text()), run / "labels.json")
    assert result == {"precision": 1.0, "recall": 1.0, "true_positive": 10,
                      "false_positive": 0, "false_negative": 0}
