"""
Danh gia Precision / Recall cua clustering + anomaly score, dua tren labeled_incidents.json.

GitHub evidence: "precision/recall". Chay sau khi da co du lieu that + labeled_incidents.json
duoc dien day du.

TODO (Nam): thay ham `_cluster_overlaps_incident` bang logic doi chieu that
(so khung thoi gian + service + signature giua cluster du doan va incident da gan nhan).
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.clustering import make_cluster_id

_LABELED_PATH = Path(__file__).with_name("labeled_incidents.json")


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evaluation timestamps must include timezone")
    return parsed.astimezone(timezone.utc)


def _cluster_overlaps_incident(cluster, incident):
    """Placeholder: coi la trung neu cung service va signature khop.

    TODO: so sanh them khung thoi gian (first_seen/last_seen vs window_from/window_to).
    """
    start, end = timestamp(incident["window_from"]), timestamp(incident["window_to"])
    first, last = timestamp(cluster["first_seen"]), timestamp(cluster["last_seen"])
    if start >= end or first > last:
        raise ValueError("Invalid incident or cluster interval")
    signature = incident["expected_cluster_signature"]
    return (cluster.get("signature") == signature
            and cluster["cluster_id"] == make_cluster_id(incident["service"], signature)
            and first < end and last >= start)


def evaluate(predicted_clusters, labeled_path=_LABELED_PATH, *, statuses=("anomalous", "alerted")):
    """predicted_clusters: danh sach cluster co status == 'alerted' (he thong da bao).

    Tra ve {"precision": float, "recall": float, "true_positive": int,
            "false_positive": int, "false_negative": int}
    """
    incidents = json.loads(Path(labeled_path).read_text(encoding="utf-8-sig"))["incidents"]
    if len({item["incident_id"] for item in incidents}) != len(incidents):
        raise ValueError("Duplicate incident_id")
    predictions = [c for c in predicted_clusters if c["status"] in statuses]
    edges = [[i for i, incident in enumerate(incidents) if _cluster_overlaps_incident(c, incident)]
             for c in predictions]
    matched = {}

    def assign(prediction, visited):
        for incident in edges[prediction]:
            if incident in visited:
                continue
            visited.add(incident)
            if incident not in matched or assign(matched[incident], visited):
                matched[incident] = prediction
                return True
        return False

    tp = sum(assign(p, set()) for p in range(len(predictions)))
    return {"precision": round(tp / len(predictions), 3) if predictions else 0.0,
            "recall": round(tp / len(incidents), 3) if incidents else 0.0,
            "true_positive": tp, "false_positive": len(predictions) - tp,
            "false_negative": len(incidents) - tp}


if __name__ == "__main__":
    # TODO: thay [] bang danh sach cluster that (status == "alerted") lay tu storage.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path, help="JSON array of ClusterRecords")
    parser.add_argument("--labels", type=Path, default=_LABELED_PATH)
    parser.add_argument("--alerted-only", action="store_true")
    args = parser.parse_args()
    predicted = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
    print(json.dumps(evaluate(predicted, args.labels,
          statuses=("alerted",) if args.alerted_only else ("anomalous", "alerted")), indent=2))
