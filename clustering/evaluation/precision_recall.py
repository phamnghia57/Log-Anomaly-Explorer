"""
Danh gia Precision / Recall cua clustering + anomaly score, dua tren labeled_incidents.json.

GitHub evidence: "precision/recall". Chay sau khi da co du lieu that + labeled_incidents.json
duoc dien day du.

TODO (Nam): thay ham `_cluster_overlaps_incident` bang logic doi chieu that
(so khung thoi gian + service + signature giua cluster du doan va incident da gan nhan).
"""

from __future__ import annotations

import json
from pathlib import Path

_LABELED_PATH = Path(__file__).resolve().parent / "labeled_incidents.json"


def _cluster_overlaps_incident(cluster: dict, incident: dict) -> bool:
    """Placeholder: coi la trung neu cung service va signature khop.

    TODO: so sanh them khung thoi gian (first_seen/last_seen vs window_from/window_to).
    """
    return (
        cluster.get("signature") == incident.get("expected_cluster_signature")
        and cluster.get("service") == incident.get("service")
    )


def evaluate(predicted_clusters: list[dict], labeled_path: Path = _LABELED_PATH) -> dict:
    """predicted_clusters: danh sach cluster co status == 'alerted' (he thong da bao).

    Tra ve {"precision": float, "recall": float, "true_positive": int,
            "false_positive": int, "false_negative": int}
    """
    incidents = json.loads(labeled_path.read_text(encoding="utf-8"))["incidents"]

    matched_incidents = set()
    true_positive = 0
    for cluster in predicted_clusters:
        hit = False
        for incident in incidents:
            if _cluster_overlaps_incident(cluster, incident):
                matched_incidents.add(incident["incident_id"])
                hit = True
        if hit:
            true_positive += 1

    false_positive = len(predicted_clusters) - true_positive
    false_negative = len(incidents) - len(matched_incidents)

    precision = true_positive / len(predicted_clusters) if predicted_clusters else 0.0
    recall = len(matched_incidents) / len(incidents) if incidents else 0.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


if __name__ == "__main__":
    # TODO: thay [] bang danh sach cluster that (status == "alerted") lay tu storage.
    print(evaluate(predicted_clusters=[]))
