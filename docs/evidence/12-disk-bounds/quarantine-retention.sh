#!/usr/bin/env bash
# Evidence #109 - retention cho logs-quarantine: _count truoc/sau MOT luot
# run_quarantine_retention tren VM, dung code dang chay trong container ingestion.
#
# Chay tu goc repo tren VM (sau khi deploy ban co QUARANTINE_RETENTION_DAYS):
#   bash docs/evidence/12-disk-bounds/quarantine-retention.sh            # dung QUARANTINE_RETENTION_DAYS cua container
#   bash docs/evidence/12-disk-bounds/quarantine-retention.sh --dry-run  # chi dem, KHONG xoa
#   DAYS=7 bash docs/evidence/12-disk-bounds/quarantine-retention.sh     # ha so ngay CHI cho luot nay
#
# CANH BAO: logs-quarantine KHONG nam trong snapshot (deploy/backup.sh loai -logs-*),
# document da xoa la mat han. Ha DAYS thi script hoi xac nhan (YES=1 de bo qua).
#
# Chi chay phan quarantine (run_quarantine_retention), KHONG dong vao index log
# chinh - phan do van do job nen hang gio cua ingestion lo.
set -euo pipefail
cd "$(dirname "$0")/../../.."
[ -f docker-compose.yml ] || { echo "phai chay tu goc repo" >&2; exit 2; }

OUT="${OUT:-docs/evidence/12-disk-bounds/quarantine-retention.txt}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1
DAYS="${DAYS:-}"

if [ -n "$DAYS" ] && [ "$DRY_RUN" = "0" ] && [ "${YES:-}" != "1" ]; then
	read -r -p "Xoa that cac ban ghi quarantine cu hon ${DAYS} ngay (khong co trong backup)? [y/N] " ans
	[ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "huy"; exit 1; }
fi

{
	echo "# Evidence #109 - retention logs-quarantine (delete_by_query theo received_at)"
	echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ) tren $(hostname), git $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
	echo "# dry_run=$DRY_RUN DAYS_override=${DAYS:-<khong>}"
	echo
	docker compose exec -T -e DAYS="$DAYS" -e DRY_RUN="$DRY_RUN" ingestion python - <<'PY'
import json, os
from datetime import datetime, timedelta, timezone
from ingestion.src import config
from ingestion.src.retention import run_quarantine_retention
from ingestion.src.storage import build_store

store = build_store()
idx = store.quarantine_index
days = int(os.environ["DAYS"]) if os.environ.get("DAYS") else config.QUARANTINE_RETENTION_DAYS
cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
old_q = {"query": {"range": {"received_at": {"lt": cutoff}}}}

def count(body=None):
    return store.client.count(index=idx, body=body or {"query": {"match_all": {}}})["count"]

def span():
    r = store.client.search(index=idx, body={"size": 0, "aggs": {
        "cu_nhat": {"min": {"field": "received_at"}}, "moi_nhat": {"max": {"field": "received_at"}}}})
    a = r["aggregations"]
    return a["cu_nhat"].get("value_as_string"), a["moi_nhat"].get("value_as_string")

print(f"index={idx} QUARANTINE_RETENTION_DAYS(container)={config.QUARANTINE_RETENTION_DAYS} days_dung={days}")
print(f"cutoff={cutoff}")
print(f"TRUOC: _count tong={count()}  _count received_at<cutoff={count(old_q)}  received_at min/max={span()}")
if os.environ.get("DRY_RUN") == "1":
    print("dry-run: khong xoa")
else:
    deleted = run_quarantine_retention(store, retention_days=days)
    print(f"run_quarantine_retention: deleted={deleted}")
    print(f"SAU:   _count tong={count()}  _count received_at<cutoff={count(old_q)}  received_at min/max={span()}")
PY
	echo
	echo "## _cat/indices/logs-quarantine"
	docker compose exec -T opensearch curl -sS 'localhost:9200/_cat/indices/logs-quarantine?v&h=index,docs.count,docs.deleted,store.size'
	echo
	echo "## Log job nen gan nhat (retention hang gio)"
	docker compose logs ingestion --since 2h --no-log-prefix 2>&1 | grep -E 'retention|quarantine' | tail -5 || true
} 2>&1 | tee "$OUT"
echo "-> $OUT"
