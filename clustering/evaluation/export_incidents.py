"""Export operator-confirmed incidents for precision_recall.py --labels."""

import argparse
import json
from pathlib import Path

from clustering.src.incidents import IncidentRepository, utc_timestamp
from clustering.src.storage import OpenSearchStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", required=True, type=utc_timestamp)
    parser.add_argument("--to", dest="end", required=True, type=utc_timestamp)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.start >= args.end:
        parser.error("--from must be earlier than --to")
    store = OpenSearchStore()
    try:
        labels = IncidentRepository(store).export_confirmed(args.start, args.end)
    finally:
        store.close()
    args.output.write_text(json.dumps({"incidents": labels}, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
