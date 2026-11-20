"""Lay token/chi phi/do tre tu Langfuse cho tung cau cua golden set #108.

Ghep generation voi cau hoi bang sessionId (= cluster_id) + cua so thoi gian
[asked_at, asked_at + latency_s], lay tu chinh scores-round*.csv cua runner.
Khong dung tag de phan biet hai luot - hai luot phan biet bang THOI GIAN, dung
nhu README cua Manh ghi.

Chay trong container query-api (co LANGFUSE_* trong env):
    docker compose exec -T query-api python /tmp/langfuse_summary.py /out

Doc  /out/scores-round1.csv va /out/scores-round2.csv
Ghi  /out/langfuse-per-question.csv va /out/langfuse-summary.csv
"""
import csv
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

OUT = sys.argv[1] if len(sys.argv) > 1 else "/out"
BASE = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
AUTH = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
# Generation bat dau hoi tre so voi luc runner goi API.
SLACK_BEFORE = timedelta(seconds=5)
# Cau cuoi cua moi luot: khong co cau sau de chan, nen phai chan bang tay.
TAIL = timedelta(seconds=120)

# Cua so cua tung luot, lay tu dong cuoi runner in ra ("Cua so de loc tren
# Langfuse: <started_at> .. <ended_at>"). BAT BUOC phai chan cung bang hai moc
# nay: hai luot cach nhau chi 4,4 giay va dung lai 4 cluster giong nhau, nen
# neu chi suy cua so tu asked_at thi generation cua luot 2 se bi gan cho cau
# cuoi cua luot 1 tren cung session.
ROUNDS = [
    ("MAX_TOOL_ROUNDS=1", "scores-round1.csv",
     "2026-11-20T03:53:47.960354+00:00", "2026-11-20T03:59:33.460484+00:00"),
    ("MAX_TOOL_ROUNDS=2", "scores-round2.csv",
     "2026-11-20T03:59:37.906960+00:00", "2026-11-20T04:05:35.476779+00:00"),
]


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_generations(start, end):
    """Moi GENERATION trong [start, end], theo het cursor."""
    items, cursor = [], None
    with httpx.Client(timeout=60, auth=AUTH) as client:
        while True:
            params = {"fields": "core,basic,usage", "type": "GENERATION",
                      "fromStartTime": start.isoformat(), "toStartTime": end.isoformat(),
                      "limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = client.get(BASE + "/api/public/v2/observations", params=params)
            response.raise_for_status()
            body = response.json()
            page = body.get("data") or []
            items.extend(page)
            cursor = (body.get("meta") or {}).get("cursor")
            if not cursor or not page:
                return items


def p95(values):
    """Nearest rank: vi tri ceil(0.95*n) trong danh sach tang dan."""
    if not values:
        return ""
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 6)


def mean(values):
    return round(sum(values) / len(values), 6) if values else ""


def main():
    per_question = []
    summary = []

    for config, filename, round_start, round_end in ROUNDS:
        path = os.path.join(OUT, filename)
        if not os.path.exists(path):
            print("bo qua, khong co " + path)
            continue
        with open(path, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        window_from = parse(round_start) - SLACK_BEFORE
        window_to = parse(round_end)
        generations = fetch_generations(window_from, window_to)

        # Cac cau duoc hoi TUAN TU, va 4 cau lien tiep dung chung mot cluster ->
        # khong duoc ghep bang "cua so quanh asked_at" (cua so se chong len cau
        # sau). Moi generation thuoc ve cau GAN NHAT TRUOC no tren cung session.
        bucket = {row["id"]: [] for row in rows}
        ordered = sorted(rows, key=lambda r: parse(r["asked_at"]))
        for generation in generations:
            session = generation.get("sessionId")
            start = parse(generation["startTime"])
            owner = None
            for row in ordered:
                if row["cluster_id"] != session:
                    continue
                if parse(row["asked_at"]) - SLACK_BEFORE <= start:
                    owner = row          # cau sau ghi de -> giu cau gan nhat truoc
            if owner is not None:
                bucket[owner["id"]].append(generation)
        matched = sum(len(v) for v in bucket.values())
        print(f"{config}: {len(rows)} cau, {len(generations)} generation trong cua so, "
              f"ghep duoc {matched}")

        for row in rows:
            mine = bucket[row["id"]]
            per_question.append({
                "config": config,
                "id": row["id"],
                "cluster_id": row["cluster_id"],
                "asked_at": row["asked_at"],
                "co_loi": "co" if row["error"] else "",
                "so_generation": len(mine),
                "tokens_in": sum(g.get("inputUsage") or 0 for g in mine),
                "tokens_out": sum(g.get("outputUsage") or 0 for g in mine),
                "tokens_total": sum(g.get("totalUsage") or 0 for g in mine),
                "cost_usd": round(sum(g.get("totalCost") or 0 for g in mine), 8),
                "model_latency_s": round(sum(g.get("latency") or 0 for g in mine), 3),
                "api_latency_s": row["latency_s"],
            })

        mapped = [q for q in per_question if q["config"] == config]
        covered = [q for q in mapped if q["so_generation"] > 0]
        costed = [q for q in covered if q["cost_usd"] > 0]
        orphan = len(generations) - sum(q["so_generation"] for q in mapped)
        api_latencies = []
        for q in covered:
            try:
                api_latencies.append(float(q["api_latency_s"]))
            except ValueError:
                pass
        summary.append({
            "config": config,
            "so_cau": len(mapped),
            "so_cau_loi_api": sum(1 for q in mapped if q["co_loi"]),
            "so_cau_co_telemetry": len(covered),
            "coverage": f"{len(covered)}/{len(mapped)}",
            "so_generation": sum(q["so_generation"] for q in mapped),
            "generation_khong_ghep_duoc": orphan,
            "tokens_in_tb": mean([q["tokens_in"] for q in covered]),
            "tokens_out_tb": mean([q["tokens_out"] for q in covered]),
            "tokens_total_tb": mean([q["tokens_total"] for q in covered]),
            "cost_tb_usd": mean([q["cost_usd"] for q in costed]),
            "cost_tong_usd": round(sum(q["cost_usd"] for q in mapped), 8),
            "so_cau_co_cost": len(costed),
            "model_latency_tb_s": mean([q["model_latency_s"] for q in covered]),
            "model_latency_p95_s": p95([q["model_latency_s"] for q in covered]),
            "api_latency_tb_s": mean(api_latencies),
            "api_latency_p95_s": p95(api_latencies),
            "currency": "USD",
            "cua_so_tu": round_start,
            "cua_so_den": round_end,
        })

    if per_question:
        path = os.path.join(OUT, "langfuse-per-question.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(per_question[0].keys()))
            writer.writeheader()
            writer.writerows(per_question)
        print("da ghi " + path)
    if summary:
        path = os.path.join(OUT, "langfuse-summary.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
            writer.writeheader()
            writer.writerows(summary)
        print("da ghi " + path)
        for row in summary:
            print()
            for key, value in row.items():
                print(f"  {key:28} {value}")


if __name__ == "__main__":
    main()
