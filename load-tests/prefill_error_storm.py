"""Nap truoc baseline cho phep do error storm (issue #103).

Worker doc ``HISTORY_WINDOWS + 1`` cua so (mac dinh 31 x 60 giay) moi chu ky.
Chay Locust 5 phut tren index trong thi worker chi thay ~5 cua so -> ``logs_read``
va chi phi TF-IDF thap hon han luc bao loi da keo dai 31 phut. Script nay gui
``--minutes`` phut log ERROR **lui thoi gian** (cung bo sinh 03a, cung seed voi
``ErrorStormUser``) voi dung ``--rate`` log/giay, qua ``POST /ingest/batch``, de
chu ky dau tien cua phep do da doc du baseline.

Chi chay tren index rieng (``LOG_INDEX=storm-logs``) - xem load-tests/README.md.
Chi dung thu vien chuan + bo sinh trong repo; chay tu thu muc goc repo:

    python3 load-tests/prefill_error_storm.py --rate 10 --minutes 30 \
        --host http://localhost:9000 --report docs/evidence/07-worker-load/prefill-10.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def load_templates(seed: int) -> list[dict]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from clustering.evaluation.generate_timeline import generate_timeline

    logs, _, _ = generate_timeline(seed=seed)
    return logs


def iter_payloads(templates: list[dict], *, rate: int, minutes: int, end: datetime) -> Iterator[dict]:
    """``rate * 60 * minutes`` log, cach deu 1/rate giay, ket thuc ngay truoc ``end``.

    Generator: KHONG dung san ca list. O ``--rate 100 --minutes 30`` la 180.000 dict
    (~200-400 MB) tren VM 4 GB dang chay OpenSearch + 7 container - OOM giua chung
    se phai chay lai ca muc tai."""
    total = rate * 60 * minutes
    start = end - timedelta(minutes=minutes)
    step = 1.0 / rate
    for i in range(total):
        original = templates[i % len(templates)]
        ts = start + timedelta(seconds=i * step)
        yield {**original, "timestamp": ts.isoformat(),
               "trace_id": uuid4().hex, "span_id": uuid4().hex[:16]}


def iter_batches(payloads: Iterable[dict], batch_size: int) -> Iterator[list[dict]]:
    """Cat ``payloads`` thanh tung batch <= ``batch_size``; chi giu 1 batch trong bo nho."""
    iterator = iter(payloads)
    while batch := list(islice(iterator, batch_size)):
        yield batch


def build_payloads(templates: list[dict], *, rate: int, minutes: int, end: datetime) -> list[dict]:
    """Ban list cua ``iter_payloads`` - CHI de test/debug voi so nho, main() khong dung."""
    return list(iter_payloads(templates, rate=rate, minutes=minutes, end=end))


def post_batch(host: str, batch: list[dict], *, timeout: float = 30.0) -> tuple[int, dict]:
    req = urllib.request.Request(f"{host.rstrip('/')}/ingest/batch",
                                 data=json.dumps(batch).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rate", type=int, choices=(10, 50, 100), required=True)
    parser.add_argument("--minutes", type=int, default=30, help="so cua so baseline (mac dinh = HISTORY_WINDOWS)")
    parser.add_argument("--host", default="http://localhost:9000")
    parser.add_argument("--seed", type=int, default=98)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-retries", type=int, default=20)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.minutes < 1 or not 1 <= args.batch_size <= 500:
        parser.error("--minutes >= 1 va 1 <= --batch-size <= 500")

    end = datetime.now(timezone.utc)
    templates = load_templates(args.seed)
    started = time.monotonic()
    planned = accepted = rejected = retries_429 = 0
    first_ts = last_ts = None
    for batch in iter_batches(iter_payloads(templates, rate=args.rate, minutes=args.minutes, end=end),
                              args.batch_size):
        offset = planned
        planned += len(batch)
        first_ts = first_ts or batch[0]["timestamp"]
        last_ts = batch[-1]["timestamp"]
        for attempt in range(args.max_retries + 1):
            status, body = post_batch(args.host, batch)
            if status == 429 and attempt < args.max_retries:
                retries_429 += 1
                time.sleep(1)
                continue
            break
        if status == 202 and body.get("accepted"):
            accepted += body.get("accepted_count", len(batch))
        else:
            rejected += len(batch)
            print(f"batch @{offset}: HTTP {status}", file=sys.stderr)

    report = {
        "rate": args.rate, "minutes": args.minutes, "seed": args.seed,
        "first_timestamp": first_ts, "last_timestamp": last_ts,
        "planned": planned, "accepted": accepted, "rejected": rejected,
        "retries_429": retries_429, "elapsed_seconds": round(time.monotonic() - started, 2),
        "host": args.host,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    return 0 if rejected == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
