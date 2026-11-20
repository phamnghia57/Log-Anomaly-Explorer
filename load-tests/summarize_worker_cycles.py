"""Tong hop evidence error storm (issue #103) thanh bang cho load-tests/README.md.

Doc trong thu muc evidence (mac dinh docs/evidence/07-worker-load/), voi moi RATE:

* ``cycle-<R>.csv``          - heartbeat do capture_worker_cycles.py ghi
* ``worker-<R>.log``         - ``docker compose logs clustering`` cung khoang thoi gian
                               (nguon chinh de dem cua so: khong bi lo nhip polling)
* ``storm-<R>_stats.csv``    - Locust ``--csv``
* ``storm-<R>_failures.csv`` - Locust ``--csv`` (dem 429 / loi khac)
* ``prefill-<R>.json``       - (tuy chon) ket qua prefill_error_storm.py
* ``run-<R>.json``           - (tuy chon) metadata do run_worker_storm.sh ghi

Ghi ``summary.json``, ``summary.md``; neu co chu ky > 30 giay thi ghi them
``issue-step2.md`` (than issue cho buoc 2 cua #103). ``--update-readme`` thay
doan giua hai marker ``<!-- worker-storm:begin -->`` / ``<!-- worker-storm:end -->``.

    python3 load-tests/summarize_worker_cycles.py \
        --evidence docs/evidence/07-worker-load --update-readme load-tests/README.md
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from datetime import datetime
from pathlib import Path

RATES = (10, 50, 100)
WINDOW_SECONDS = 60
STEP2_THRESHOLD = 30.0
REPRESENTATIVE_RATIO = 0.95
BEGIN, END = "<!-- worker-storm:begin -->", "<!-- worker-storm:end -->"
LOG_LINE = re.compile(r"Processed (\S+): cycle_seconds=([0-9.]+) logs_read=(\d+) clusters_out=(\d+)")


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty")
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def read_cycles_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("window_to") and _f(row.get("cycle_seconds")) is not None:
                rows.append({"window_to": row["window_to"], "cycle_seconds": float(row["cycle_seconds"]),
                             "logs_read": int(float(row.get("logs_read") or 0)),
                             "clusters_out": int(float(row.get("clusters_out") or 0)),
                             "processed_at": row.get("last_processed_at")})
    return rows


def read_worker_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LOG_LINE.search(line)
        if match:
            rows.append({"window_to": match[1], "cycle_seconds": float(match[2]),
                         "logs_read": int(match[3]), "clusters_out": int(match[4]), "processed_at": None})
    return rows


def window_gaps(windows: list[str]) -> tuple[list[int], int]:
    """Khoang cach (giay) giua cac window_to lien tiep va so cua so bi bo qua."""
    ordered = sorted({_ts(w) for w in windows})
    gaps = [int((b - a).total_seconds()) for a, b in zip(ordered, ordered[1:])]
    missed = sum(max(0, gap // WINDOW_SECONDS - 1) for gap in gaps)
    return gaps, missed


def read_locust(stats: Path, failures: Path) -> dict | None:
    if not stats.exists():
        return None
    row = None
    with stats.open(newline="", encoding="utf-8") as fh:
        for candidate in csv.DictReader(fh):
            if "ERROR storm" in candidate.get("Name", ""):
                row = candidate
            elif row is None and candidate.get("Name") == "Aggregated":
                row = candidate
    if row is None:
        return None
    requests = int(row["Request Count"])
    failed = int(row["Failure Count"])
    status_429 = 0
    if failures.exists():
        with failures.open(newline="", encoding="utf-8") as fh:
            for item in csv.DictReader(fh):
                if "429" in item.get("Error", ""):
                    status_429 += int(item.get("Occurrences") or 0)
    return {"requests": requests, "accepted_202": requests - failed, "status_429": status_429,
            "other_errors": failed - status_429, "rps": _f(row.get("Requests/s")) or 0.0,
            "median_ms": _f(row.get("Median Response Time")), "p95_ms": _f(row.get("95%"))}


def summarize_rate(evidence: Path, rate: int) -> dict:
    log_rows = read_worker_log(evidence / f"worker-{rate}.log")
    csv_rows = read_cycles_csv(evidence / f"cycle-{rate}.csv")
    # Chi tinh cac chu ky trong khoang collector chay (CSV); log worker co the dai hon.
    if csv_rows and log_rows:
        lo = min(_ts(r["window_to"]) for r in csv_rows)
        hi = max(_ts(r["window_to"]) for r in csv_rows)
        log_rows = [r for r in log_rows if lo <= _ts(r["window_to"]) <= hi]
    rows = log_rows or csv_rows
    source = "worker-log" if log_rows else ("cycle-csv" if csv_rows else None)
    result = {"rate": rate, "measured": bool(rows), "source": source}
    meta_path, prefill_path = evidence / f"run-{rate}.json", evidence / f"prefill-{rate}.json"
    result["run"] = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
    result["prefill"] = json.loads(prefill_path.read_text(encoding="utf-8")) if prefill_path.exists() else None
    result["locust"] = read_locust(evidence / f"storm-{rate}_stats.csv", evidence / f"storm-{rate}_failures.csv")
    if not rows:
        return result
    seconds = [r["cycle_seconds"] for r in rows]
    gaps, missed = window_gaps([r["window_to"] for r in rows])
    delays = [(_ts(r["processed_at"]) - _ts(r["window_to"])).total_seconds()
              for r in csv_rows if r.get("processed_at")]
    result.update(cycles=len(rows), cycle_min=min(seconds), cycle_median=statistics.median(seconds),
                  cycle_p95=percentile(seconds, 95), cycle_max=max(seconds),
                  logs_read_max=max(r["logs_read"] for r in rows),
                  clusters_out_max=max(r["clusters_out"] for r in rows),
                  window_gaps=gaps, missed_windows=missed,
                  csv_missed_windows=window_gaps([r["window_to"] for r in csv_rows])[1] if csv_rows else None,
                  max_delay_after_window=max(delays) if delays else None,
                  over_threshold=[r for r in rows if r["cycle_seconds"] > STEP2_THRESHOLD])
    locust = result["locust"]
    prefill = result["prefill"]
    result["rate_reached"] = bool(locust) and locust["rps"] >= REPRESENTATIVE_RATIO * rate and locust["status_429"] == 0
    result["baseline_full"] = bool(prefill) and prefill.get("rejected") == 0 and prefill.get("minutes", 0) >= 30
    return result


def _fmt(value, digits=2, suffix=" s") -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def table(results: list[dict]) -> str:
    lines = ["| Mức mục tiêu | Throughput thực | 202 / 429 / lỗi khác | Baseline nạp trước | Số chu kỳ |"
             " cycle_seconds median / p95 / max | logs_read max | Cửa sổ lỡ | Đại diện mức tải? |",
             "|---:|---:|---|---|---:|---|---:|---|---|"]
    for r in results:
        label = f"{r['rate']} ERROR/s"
        if not r["measured"]:
            lines.append(f"| {label} | — | — | — | — | Chưa đo | — | Chưa xác định | — |")
            continue
        lo = r["locust"]
        thr = f"{lo['rps']:.1f} req/s" if lo else "thiếu Locust CSV"
        codes = f"{lo['accepted_202']} / {lo['status_429']} / {lo['other_errors']}" if lo else "—"
        pf = r["prefill"]
        base = (f"{pf['minutes']} phút, {pf['accepted']} log" if pf else "không (index trống)")
        cyc = f"{_fmt(r['cycle_median'], 3)} / {_fmt(r['cycle_p95'], 3)} / **{_fmt(r['cycle_max'], 3)}**"
        missed = "không" if r["missed_windows"] == 0 else f"**{r['missed_windows']}**"
        rep = "có" if r["rate_reached"] else "**không** (chưa đạt RATE hoặc có 429)"
        lines.append(f"| {label} | {thr} | {codes} | {base} | {r['cycles']} | {cyc} | {r['logs_read_max']} |"
                     f" {missed} | {rep} |")
    return "\n".join(lines)


def conclusion(results: list[dict]) -> list[str]:
    measured = [r for r in results if r["measured"]]
    if not measured:
        return ["Chưa có số đo nào trong thư mục evidence."]
    out = []
    first_miss = next((r for r in measured if r["missed_windows"]), None)
    if first_miss:
        out.append(f"- **Worker bắt đầu lỡ cửa sổ ở mức {first_miss['rate']} ERROR/s**: "
                   f"{first_miss['missed_windows']} cửa sổ bị bỏ, khoảng cách `window_to` liên tiếp "
                   f"{sorted(set(first_miss['window_gaps']))} giây (đúng phải là {WINDOW_SECONDS}).")
    else:
        rates = ", ".join(str(r["rate"]) for r in measured)
        sources = {"worker-log": "log worker", "cycle-csv": "CSV collector"}
        src = " + ".join(sorted({sources[r["source"]] for r in measured}))
        out.append(f"- **Không lỡ cửa sổ nào** ở các mức đã đo ({rates} ERROR/s): mọi `window_to` "
                   f"liên tiếp cách nhau đúng {WINDOW_SECONDS} giây (đếm từ {src}).")
    slow = [r for r in measured if r["over_threshold"]]
    if slow:
        worst = max(slow, key=lambda r: r["cycle_max"])
        out.append(f"- Có chu kỳ `cycle_seconds > {STEP2_THRESHOLD:.0f}` (lớn nhất {worst['cycle_max']:.1f} s ở "
                   f"{worst['rate']} ERROR/s) → **cần bước 2 của #103**, xem `issue-step2.md`.")
    else:
        worst = max(measured, key=lambda r: r["cycle_max"])
        out.append(f"- Không chu kỳ nào vượt {STEP2_THRESHOLD:.0f} s (lớn nhất {worst['cycle_max']:.2f} s ở "
                   f"{worst['rate']} ERROR/s) → **chưa cần bước 2** (lấy mẫu TF-IDF, chặn trần `log_ids`).")
    for r in measured:
        if not r["rate_reached"]:
            lo = r["locust"]
            got = f"{lo['rps']:.1f} req/s, {lo['status_429']} lần 429" if lo else "không có Locust CSV"
            out.append(f"- Mức {r['rate']} ERROR/s **không đại diện** đúng mức đó ({got}).")
        if not r["baseline_full"]:
            out.append(f"- Mức {r['rate']} ERROR/s **không nạp đủ 30 cửa sổ baseline** → `logs_read` thấp hơn "
                       f"bão lỗi kéo dài 31 phút.")
        if r.get("csv_missed_windows") and r["source"] == "worker-log" and not r["missed_windows"]:
            out.append(f"- Mức {r['rate']}: collector lỡ {r['csv_missed_windows']} heartbeat nhưng log worker đủ "
                       f"cửa sổ → là lỗi polling, không phải worker bỏ cửa sổ.")
    return out


def environment(results: list[dict]) -> list[str]:
    run = next((r["run"] for r in results if r.get("run")), None)
    if not run:
        return ["- Chưa có `run-<R>.json` (metadata máy đo)."]
    keys = (("git_sha", "Commit"), ("nproc", "vCPU"), ("mem_total", "RAM"), ("cpu_model", "CPU"),
            ("opensearch_heap", "OpenSearch heap"), ("seed", "Seed"), ("history_windows", "HISTORY_WINDOWS"))
    out = [f"- {label}: `{run[key]}`" for key, label in keys if run.get(key) not in (None, "")]
    for r in results:
        meta = r.get("run")
        if meta:
            out.append(f"- Mức {r['rate']}: {meta.get('locust_users')} Locust user × {meta.get('per_user_rps')} req/s,"
                       f" `INGEST_RATE_LIMIT_RPS={meta.get('ingest_rate_limit_rps')}` lúc đo,"
                       f" prefill {meta.get('prefill_minutes')} phút, bắt đầu {meta.get('started_at')}")
    out.append("- Máy đo là VM deploy, CPU dùng chung với OpenSearch + Jaeger + demo-app + query-api đang chạy.")
    return out


def render(results: list[dict]) -> str:
    dates = sorted({r["run"]["started_at"][:10] for r in results if r.get("run") and r["run"].get("started_at")})
    head = f"Đo ngày {', '.join(dates)}." if dates else "Ngày đo: xem `run-<R>.json`."
    return "\n".join([head, "", table(results), "", "**Kết luận**", "", *conclusion(results), "",
                      "**Cấu hình máy đo**", "", *environment(results), "",
                      "Số liệu gốc: [`docs/evidence/07-worker-load/`](../docs/evidence/07-worker-load/)"
                      " — sinh lại bằng `python3 load-tests/summarize_worker_cycles.py`."])


def issue_body(results: list[dict]) -> str:
    slow = [(r["rate"], row) for r in results if r["measured"] for row in r["over_threshold"]]
    lines = ["## perf(clustering): bước 2 của #103 — lấy mẫu TF-IDF, chặn trần `log_ids`", "",
             f"Phép đo error storm trên VM có {len(slow)} chu kỳ `cycle_seconds > {STEP2_THRESHOLD:.0f}`:", "",
             "| Mức | window_to | cycle_seconds | logs_read | clusters_out |", "|---:|---|---:|---:|---:|"]
    lines += [f"| {rate} | {row['window_to']} | {row['cycle_seconds']:.2f} | {row['logs_read']} | {row['clusters_out']} |"
              for rate, row in slow]
    lines += ["", "Evidence: `docs/evidence/07-worker-load/`, bảng trong `load-tests/README.md`.", "",
              "Việc cần làm: lấy mẫu đầu vào TF-IDF khi `logs_read` lớn; chặn trần số `log_ids` lưu mỗi cụm;"
              " đo lại cùng quy trình để xác nhận `cycle_seconds` < 30 s ở mức đã vượt."]
    return "\n".join(lines) + "\n"


def replace_block(text: str, block: str) -> str:
    if BEGIN not in text or END not in text:
        raise SystemExit(f"README thieu marker {BEGIN} / {END}")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{block}\n{END}{tail}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", type=Path, default=Path("docs/evidence/07-worker-load"))
    parser.add_argument("--update-readme", type=Path)
    args = parser.parse_args(argv)
    results = [summarize_rate(args.evidence, rate) for rate in RATES]
    block = render(results)
    (args.evidence / "summary.md").write_text(block + "\n", encoding="utf-8")
    (args.evidence / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str) + "\n",
                                                encoding="utf-8")
    if any(r["measured"] and r["over_threshold"] for r in results):
        (args.evidence / "issue-step2.md").write_text(issue_body(results), encoding="utf-8")
    if args.update_readme:
        args.update_readme.write_text(replace_block(args.update_readme.read_text(encoding="utf-8"), block),
                                      encoding="utf-8")
    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
