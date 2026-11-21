"""Unit tests cho cong cu do error storm (#103): khong can Docker/OpenSearch."""

import csv
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summarize = _load("summarize_worker_cycles")
prefill = _load("prefill_error_storm")

T0 = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)


def _write_cycles(path, windows, seconds):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=("target_errors_per_second", "observed_at", "last_processed_at",
                                                "window_to", "cycle_seconds", "logs_read", "clusters_out"))
        writer.writeheader()
        for window, cycle in zip(windows, seconds):
            writer.writerow({"target_errors_per_second": 10, "observed_at": "",
                             "last_processed_at": (window + timedelta(seconds=10 + cycle)).isoformat(),
                             "window_to": window.isoformat(), "cycle_seconds": cycle,
                             "logs_read": 18000, "clusters_out": 7})


def _write_locust(evidence, rate, requests, failures, rps, n429=0):
    with (evidence / f"storm-{rate}_stats.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Type", "Name", "Request Count", "Failure Count", "Median Response Time", "95%",
                         "Requests/s"])
        writer.writerow(["POST", "POST /ingest (ERROR storm)", requests, failures, 8, 18, rps])
        writer.writerow(["", "Aggregated", requests, failures, 8, 18, rps])
    with (evidence / f"storm-{rate}_failures.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Method", "Name", "Error", "Occurrences"])
        if n429:
            writer.writerow(["POST", "POST /ingest (ERROR storm)", "Expected 202; got 429", n429])
        if failures - n429:
            writer.writerow(["POST", "POST /ingest (ERROR storm)", "Expected 202; got 503", failures - n429])


def _prefill(evidence, rate, minutes=30, rejected=0):
    (evidence / f"prefill-{rate}.json").write_text(json.dumps(
        {"rate": rate, "minutes": minutes, "accepted": rate * 60 * minutes, "rejected": rejected}))


def test_window_gaps_counts_skipped_windows():
    windows = [(T0 + timedelta(minutes=m)).isoformat() for m in (0, 1, 3, 4, 7)]
    gaps, missed = summarize.window_gaps(windows)
    assert gaps == [60, 120, 60, 180]
    assert missed == 3


def test_steady_run_has_no_missed_window_and_no_step2(tmp_path):
    windows = [T0 + timedelta(minutes=m) for m in range(6)]
    _write_cycles(tmp_path / "cycle-10.csv", windows, [1.2, 1.4, 1.1, 1.3, 1.5, 1.2])
    _write_locust(tmp_path, 10, 3000, 0, 9.98)
    _prefill(tmp_path, 10)
    result = summarize.summarize_rate(tmp_path, 10)
    assert result["missed_windows"] == 0
    assert result["cycle_max"] == pytest.approx(1.5)
    assert result["rate_reached"] and result["baseline_full"]
    text = summarize.render([result, summarize.summarize_rate(tmp_path, 50), summarize.summarize_rate(tmp_path, 100)])
    assert "chưa cần bước 2" in text
    assert "Không lỡ cửa sổ nào" in text
    assert "| 50 ERROR/s | — | — | — | — | Chưa đo |" in text


def test_worker_log_is_preferred_over_polled_csv(tmp_path):
    windows = [T0 + timedelta(minutes=m) for m in range(5)]
    # Collector lo heartbeat phut thu 2, nhung log worker co du.
    _write_cycles(tmp_path / "cycle-50.csv", [w for i, w in enumerate(windows) if i != 2], [2.0] * 4)
    (tmp_path / "worker-50.log").write_text("\n".join(
        f"INFO:root:Processed {w.isoformat()}: cycle_seconds=2.000 logs_read=90000 clusters_out=9"
        for w in windows) + "\nINFO:root:Cluster history retention: deleted=0\n")
    _write_locust(tmp_path, 50, 15000, 0, 49.9)
    result = summarize.summarize_rate(tmp_path, 50)
    assert result["source"] == "worker-log"
    assert result["missed_windows"] == 0
    assert result["csv_missed_windows"] == 1
    assert result["logs_read_max"] == 90000
    assert any("lỗi polling" in line for line in summarize.conclusion([result]))


def test_slow_cycles_trigger_step2_issue_and_missed_windows(tmp_path):
    windows = [T0 + timedelta(minutes=m) for m in (0, 1, 3, 5)]
    _write_cycles(tmp_path / "cycle-100.csv", windows, [12.0, 55.0, 58.0, 41.0])
    _write_locust(tmp_path, 100, 24000, 300, 80.0, n429=300)
    summarize.main(["--evidence", str(tmp_path)])
    data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    r100 = data[2]
    assert r100["missed_windows"] == 2
    assert r100["rate_reached"] is False
    assert r100["locust"]["status_429"] == 300 and r100["locust"]["accepted_202"] == 23700
    body = (tmp_path / "issue-step2.md").read_text(encoding="utf-8")
    assert "55.00" in body and "bước 2" in body
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Worker bắt đầu lỡ cửa sổ ở mức 100" in summary
    assert "không nạp đủ 30 cửa sổ baseline" in summary


def test_readme_block_replacement_keeps_surrounding_text():
    text = f"before\n{summarize.BEGIN}\nold\n{summarize.END}\nafter\n"
    out = summarize.replace_block(text, "NEW")
    assert out == f"before\n{summarize.BEGIN}\nNEW\n{summarize.END}\nafter\n"


def test_current_readme_has_markers():
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    assert summarize.BEGIN in readme and summarize.END in readme


def test_prefill_payloads_cover_window_at_rate():
    templates = prefill.load_templates(98)
    end = T0
    payloads = prefill.build_payloads(templates, rate=10, minutes=2, end=end)
    assert len(payloads) == 1200
    first = datetime.fromisoformat(payloads[0]["timestamp"])
    last = datetime.fromisoformat(payloads[-1]["timestamp"])
    assert first == end - timedelta(minutes=2)
    assert end - timedelta(seconds=0.2) < last < end
    assert len({p["trace_id"] for p in payloads}) == 1200
    assert all(p["level"] in {"ERROR", "FATAL"} for p in payloads)


def test_prefill_retries_429_then_reports(monkeypatch, tmp_path):
    calls = []

    def fake_post(host, batch, timeout=30.0):
        calls.append(len(batch))
        if len(calls) == 1:
            return 429, {}
        return 202, {"accepted": True, "accepted_count": len(batch)}

    monkeypatch.setattr(prefill, "post_batch", fake_post)
    monkeypatch.setattr(prefill.time, "sleep", lambda _: None)
    report = tmp_path / "prefill.json"
    code = prefill.main(["--rate", "10", "--minutes", "1", "--batch-size", "500", "--report", str(report)])
    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0
    assert data["accepted"] == 600 and data["rejected"] == 0 and data["retries_429"] == 1
    assert calls == [500, 500, 100]


def test_prefill_gui_theo_batch_khong_dung_san_ca_list(monkeypatch):
    """Review PR #127: o --rate 100 --minutes 30 build_payloads cu dung 180.000 dict
    truoc batch dau (~200-400 MB tren VM 4 GB). Gio main() phai sinh lazy: luc gui
    batch dau tien, generator moi sinh toi da 1 batch."""
    produced = {"n": 0}
    real_iter = prefill.iter_payloads

    def counting_iter(*args, **kwargs):
        for item in real_iter(*args, **kwargs):
            produced["n"] += 1
            yield item

    seen_at_post = []

    def fake_post(host, batch, timeout=30.0):
        seen_at_post.append(produced["n"])
        return 202, {"accepted": True, "accepted_count": len(batch)}

    monkeypatch.setattr(prefill, "iter_payloads", counting_iter)
    monkeypatch.setattr(prefill, "post_batch", fake_post)
    assert prefill.main(["--rate", "100", "--minutes", "2", "--batch-size", "500"]) == 0
    assert len(seen_at_post) == 24  # 100 * 60 * 2 / 500
    assert seen_at_post[0] <= 501  # islice co the keo them toi da 1 phan tu
    assert all(n <= (i + 1) * 500 + 1 for i, n in enumerate(seen_at_post))


def test_iter_batches_cat_dung_kich_thuoc_va_phan_du():
    batches = list(prefill.iter_batches(iter(range(1203)), 500))
    assert [len(b) for b in batches] == [500, 500, 203]
    assert batches[-1][-1] == 1202
    assert list(prefill.iter_batches(iter(()), 500)) == []


def test_prefill_report_giu_first_last_timestamp(monkeypatch, tmp_path):
    monkeypatch.setattr(prefill, "post_batch",
                        lambda host, batch, timeout=30.0: (202, {"accepted": True, "accepted_count": len(batch)}))
    report = tmp_path / "r.json"
    assert prefill.main(["--rate", "10", "--minutes", "1", "--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    first = datetime.fromisoformat(data["first_timestamp"])
    last = datetime.fromisoformat(data["last_timestamp"])
    assert data["planned"] == 600
    assert (last - first).total_seconds() == pytest.approx(59.9, abs=0.01)
