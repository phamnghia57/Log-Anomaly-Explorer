#!/usr/bin/env bash
# Dien tap restore tren may khac (khong phai VM) va do RTO.
#
#   deploy/pull-backup.sh <user>@<vm> prj2 ./backups     # 1. keo backup ve
#   deploy/restore-drill.sh [ten-snapshot]                # 2. restore (mac dinh: ban moi nhat)
#   deploy/restore-drill.sh --down                        # 3. don dep sau khi chup anh
#
# Bien tuy chon:
#   DRILL_BACKUP_DIR   thu muc backup (mac dinh <repo>/backups)
#   DRILL_USERNAME     tai khoan admin cu -> tu dang nhap thu (hoi mat khau, khong in ra)
#   DRILL_CLUSTER_ID   cluster_id cu -> in trang thai incident sau restore
#   EVIDENCE_DIR       noi ghi restore-log.txt (docs/evidence/04-backup-restore)
#
# Windows: chay trong Git Bash hoac WSL (can Docker Desktop). Moi lenh goi
# OpenSearch deu chay BEN TRONG container nen khong phu thuoc curl cua Windows.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
export MSYS_NO_PATHCONV=1   # Git Bash: khong doi "/snapshots" thanh C:/Program Files/Git/snapshots
# Git Bash: `pwd -W` tra C:/... de Docker Desktop hieu duong dan bind mount.
DRILL_BACKUP_DIR="$(cd "${DRILL_BACKUP_DIR:-$ROOT/backups}" && { pwd -W 2>/dev/null || pwd; })"
export DRILL_BACKUP_DIR
EVIDENCE_DIR="${EVIDENCE_DIR:-$ROOT/docs/evidence/04-backup-restore}"
DC=(docker compose -f deploy/restore-drill.compose.yml)

if [ "${1:-}" = "--down" ]; then
	"${DC[@]}" --profile tools down -v
	exit 0
fi

mkdir -p "$EVIDENCE_DIR"
LOG="$EVIDENCE_DIR/restore-log.txt"
exec > >(tee "$LOG") 2>&1

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
step() { printf '\n[%s] (+%ss) %s\n' "$(now)" "$((SECONDS - T0))" "$*"; }
os() { "${DC[@]}" exec -T opensearch curl -sS "$@"; }

[ -d "$DRILL_BACKUP_DIR/os" ] || { echo "khong thay $DRILL_BACKUP_DIR/os - chay deploy/pull-backup.sh truoc" >&2; exit 2; }
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "can python3 tren may dien tap (doc JSON)" >&2; exit 2; }
# JSON luon dua qua stdin: python Windows khong mo duoc duong dan kieu /c/... cua Git Bash.

T0=$SECONDS
echo "# Restore drill - $(now)"
echo "may: $(uname -srm), docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
echo "backup: $DRILL_BACKUP_DIR"
ls -la "$DRILL_BACKUP_DIR" "$DRILL_BACKUP_DIR/clustering-data"
du -sh "$DRILL_BACKUP_DIR/os" "$DRILL_BACKUP_DIR/clustering-data"

step "don stack dien tap cu (chi project lae-restore-drill)"
"${DC[@]}" --profile tools down -v

step "khoi dong OpenSearch trong"
"${DC[@]}" up -d --wait opensearch
T_OS=$SECONDS

step "dang ky repo snapshot (readonly)"
os -XPUT 'localhost:9200/_snapshot/drill' -H 'Content-Type: application/json' \
	-d '{"type":"fs","settings":{"location":"/snapshots","readonly":true}}'
echo
os 'localhost:9200/_snapshot/drill/_all' > "$EVIDENCE_DIR/snapshot-list.json"
"$PY" -c "$(cat <<'PY'
import json, sys
snaps = sorted(json.load(sys.stdin)["snapshots"], key=lambda s: s["start_time_in_millis"])
for s in snaps:
    print(f'{s["snapshot"]:28} {s["state"]:8} {s["start_time"]}  {len(s["indices"])} indices')
PY
)" < "$EVIDENCE_DIR/snapshot-list.json"

snap="${1:-}"
if [ -z "$snap" ]; then
	snap="$("$PY" -c '
import json,sys
s=[x for x in json.load(sys.stdin)["snapshots"] if x["state"]=="SUCCESS"]
print(max(s, key=lambda x: x["start_time_in_millis"])["snapshot"])' < "$EVIDENCE_DIR/snapshot-list.json" | tr -d '\r')"
fi
SNAP="$snap" "$PY" -c "$(cat <<'PY'
import json, os, sys, time
s = next(x for x in json.load(sys.stdin)["snapshots"] if x["snapshot"] == os.environ["SNAP"])
age_h = (time.time() * 1000 - s["start_time_in_millis"]) / 3600000
logs = [i for i in s["indices"] if i == "logs" or i.startswith("logs-")]
print(f'chon {s["snapshot"]}: bat dau {s["start_time"]} (cach day {age_h:.1f} gio)')
print("indices:", ", ".join(sorted(s["indices"])))
print("index log trong snapshot:", logs or "KHONG CO (dung)")
PY
)" < "$EVIDENCE_DIR/snapshot-list.json"

step "restore $snap"
T_R=$SECONDS
restore_out="$(os -XPOST "localhost:9200/_snapshot/drill/$snap/_restore?wait_for_completion=true" \
	-H 'Content-Type: application/json' -d '{"indices":"*","include_global_state":false}')"
echo "$restore_out"
"$PY" -c '
import json, sys
d = json.load(sys.stdin)
sh = d.get("snapshot", {}).get("shards", {})
if "error" in d or sh.get("failed", 1) != 0 or not sh.get("successful"):
    sys.exit("RESTORE THAT BAI")
print("restore ok:", sh.get("successful"), "shard")' <<<"$restore_out"
os 'localhost:9200/_cluster/health?wait_for_status=yellow&timeout=120s' >/dev/null
RESTORE_S=$((SECONDS - T_R))
os 'localhost:9200/_cat/indices?v&s=index'
for idx in users clusters clusters-incidents cluster-history assistant-conversations; do
	printf '%-26s %s\n' "$idx" "$(os "localhost:9200/$idx/_count" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("count","MISSING"))')"
done

step "bung clustering-data vao volume dien tap"
tarball="$(ls -1t "$DRILL_BACKUP_DIR"/clustering-data/clustering-data-*.tar.gz | head -1)"
echo "tar: $(basename "$tarball")"
"${DC[@]}" run --rm --no-deps tools sh -ec \
	"tar xzf /in/$(basename "$tarball") -C /data && ls -la /data && wc -c /data/ml_templates.json"

step "build + khoi dong query-api tro vao OpenSearch da restore"
"${DC[@]}" up -d --build --wait query-api
T_API=$SECONDS
curl -fsS http://127.0.0.1:18002/health; echo

TOTAL_S=$((T_API - T0))

if [ -n "${DRILL_USERNAME:-}" ]; then
	step "dang nhap bang tai khoan cu '$DRILL_USERNAME'"
	read -r -s -p "Mat khau cua $DRILL_USERNAME: " DRILL_PASSWORD </dev/tty; echo
	body="$(DRILL_USERNAME="$DRILL_USERNAME" DRILL_PASSWORD="$DRILL_PASSWORD" "$PY" -c \
		'import json,os; print(json.dumps({"username":os.environ["DRILL_USERNAME"],"password":os.environ["DRILL_PASSWORD"]}))')"
	unset DRILL_PASSWORD
	resp="$(curl -sS -o - -w '\n%{http_code}' http://127.0.0.1:18002/auth/login \
		-H 'Content-Type: application/json' -H 'X-CSRF-Protection: 1' -H 'Origin: http://localhost:5173' -d "$body")"
	code="${resp##*$'\n'}"
	echo "POST /auth/login -> HTTP $code"
	if [ "$code" = "200" ] && [ -n "${DRILL_CLUSTER_ID:-}" ]; then
		token="$(printf '%s' "${resp%$'\n'*}" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["token"])' | tr -d '\r')"
		curl -sS "http://127.0.0.1:18002/clusters/$DRILL_CLUSTER_ID" -H "Authorization: Bearer $token" \
			| "$PY" -c '
import json,sys
c=json.load(sys.stdin); i=c.get("incident") or {}
print("cluster_id:", c.get("cluster_id"), "| service:", c.get("service"), "| status:", c.get("status"), "| score:", c.get("score"))
print("incident:", {k: i.get(k) for k in ("episode","status","disposition","acknowledged_by","resolved_by","window_from","window_to")})
print("logs tra ve:", len(c.get("logs", [])), "/", c.get("logs_total"), "(logs-* khong nam trong backup -> 0 la dung)")'
	fi
fi

cat <<EOF

== KET QUA ($(now)) ==
snapshot              : $snap
OpenSearch san sang   : $((T_OS - T0)) s
restore snapshot      : $RESTORE_S s
query-api healthy     : $((T_API - T0)) s tinh tu dau (gom build image)
RTO do duoc (tong)    : ${TOTAL_S} s  (~$(( (TOTAL_S + 59) / 60 )) phut)
(build image query-api lan dau mat vai phut; tren VM moi that thi image da build
 san sau deploy.sh -> RTO thuc te ~ OpenSearch + restore + khoi dong query-api)
Log day du            : $LOG

Tiep theo: mo Incident View de chup anh
  cd web && npm ci && API_PROXY_TARGET=http://localhost:18002 npm run dev
  -> http://localhost:5173 , dang nhap tai khoan cu, mo /clusters/<cluster_id cu>
Don dep: deploy/restore-drill.sh --down
EOF
