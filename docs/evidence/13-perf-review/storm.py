import argparse
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from clustering.evaluation.generate_timeline import generate_timeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=10)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--host", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    logs, _, _ = generate_timeline(seed=98)
    step = 1.0 / args.rate
    start = time.monotonic()
    counts = {}
    i = 0
    with httpx.Client(timeout=5, trust_env=False) as client:
        while time.monotonic() - start < args.seconds:
            delay = start + i * step - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            payload = {**logs[i % len(logs)], "timestamp": datetime.now(timezone.utc).isoformat(),
                       "trace_id": uuid4().hex, "span_id": uuid4().hex[:16]}
            code = client.post(f"{args.host}/ingest", json=payload).status_code
            counts[code] = counts.get(code, 0) + 1
            i += 1
    print(json.dumps({"sent": i, "codes": counts, "seconds": round(time.monotonic() - start, 1)}), flush=True)


if __name__ == "__main__":
    main()
