#!/usr/bin/env bash
# Backup hang dem: snapshot OpenSearch (tru log demo) + volume clustering-data,
# copy ra ngoai VM, xoa ban cu hon RETENTION_DAYS ngay.
#
# Chay tu bat ky dau (script tu cd ve goc repo):
#   deploy/backup.sh                  # 1 lan backup day du
#   deploy/backup.sh --list           # in danh sach snapshot + indices cua ban moi nhat
# Cron (crontab -e tren VM), vd. 02:17 gio VN = 19:17 UTC (VM chay UTC):
#   17 19 * * * /home/<user>/prj2/deploy/backup.sh >> /home/<user>/prj2/backups/backup.log 2>&1
#
# Cau hinh: bien moi truong, hoac file deploy/backup.env (KHONG commit, xem
# deploy/backup.env.example):
#   BACKUP_DIR        thu muc backup tren VM            (./backups)
#   SNAPSHOT_REPO     ten repo snapshot                 (nightly)
#   SNAPSHOT_INDICES  pattern index                     ("*,-.*,-logs,-logs-*,-storm-*")
#   RETENTION_DAYS    xoa snapshot/tar cu hon N ngay    (7)
#   MIN_KEEP          luon giu it nhat N ban moi nhat   (2)
#   BACKUP_REMOTE     dich rsync ngoai VM, vd. "backup@1.2.3.4:/srv/lae-backups"
#                     de trong = chi giu tren VM (phuong an nho: khong chong mat VM)
#   BACKUP_SSH_OPTS   tuy chon ssh cho rsync           ("-o BatchMode=yes")
#   BACKUP_PING_URL   (tuy chon) URL Healthchecks rieng cho job backup
#
# Vi sao loai `logs` + `logs-*`: log demo sinh lai duoc va la phan nang nhat.
# `logs-quarantine` khop `logs-*` nen cung bi loai. `.*` (index he thong/plugin)
# khong can va restore de bi xung dot. include_global_state=false: khong ghi de
# template/settings cua cluster dich khi restore.
set -Eeuo pipefail
export PATH="${PATH:+$PATH:}/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"  # cron co PATH toi gian

cd "$(dirname "$0")/.."
ROOT="$PWD"
[ -f deploy/backup.env ] && . deploy/backup.env

BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
SNAPSHOT_REPO="${SNAPSHOT_REPO:-nightly}"
SNAPSHOT_INDICES="${SNAPSHOT_INDICES:-*,-.*,-logs,-logs-*,-storm-*}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
MIN_KEEP="${MIN_KEEP:-2}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
BACKUP_SSH_OPTS="${BACKUP_SSH_OPTS:--o BatchMode=yes}"
BACKUP_PING_URL="${BACKUP_PING_URL:-}"
OS_UID="${OPENSEARCH_UID:-1000}"   # user `opensearch` trong image opensearchproject/opensearch

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "LOI: $*" >&2; ping_hc /fail; exit 1; }
os_curl() { docker compose exec -T opensearch curl -sS "$@"; }
# Loi OpenSearch tra JSON {"error":...}: dung lai thay vi coi nhu thanh cong.
os_ack() {
	local out; out="$(os_curl "$@")"
	grep -Eq '"acknowledged" *: *true' <<<"$out" || die "OpenSearch tu choi ($*): $out"
}
json() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }
ping_hc() { [ -n "$BACKUP_PING_URL" ] && curl -fsS -m 10 --retry 3 -o /dev/null "$BACKUP_PING_URL$1" || true; }

on_error() {
	local code=$? line=$1
	log "THAT BAI (exit $code, dong $line)" >&2
	ping_hc /fail
	exit "$code"
}
trap 'on_error $LINENO' ERR

list_snapshots() {
	os_curl "localhost:9200/_snapshot/$SNAPSHOT_REPO/_all" | json '
for s in sorted(d["snapshots"], key=lambda s: s["start_time_in_millis"]):
    print(s["snapshot"], s["state"], s["start_time"], len(s["indices"]), ",".join(sorted(s["indices"])))'
}

if [ "${1:-}" = "--list" ]; then
	list_snapshots
	exit 0
fi

mkdir -p "$BACKUP_DIR/os" "$BACKUP_DIR/clustering-data"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || die "mot lan backup khac dang chay"

stamp="$(date -u +%Y.%m.%d-%H%M)"
snap="nightly-$stamp"
log "bat dau backup $snap"
ping_hc /start

# --- 0. Kiem tra repo snapshot -------------------------------------------------
owner="$(stat -c %u "$BACKUP_DIR/os")"
[ "$owner" = "$OS_UID" ] || die "$BACKUP_DIR/os thuoc UID $owner, OpenSearch can UID $OS_UID: sudo chown -R $OS_UID:$OS_UID $BACKUP_DIR/os"
docker compose exec -T opensearch test -d /snapshots \
	|| die "container opensearch khong co /snapshots - chua recreate sau khi them path.repo?"
os_ack -XPUT "localhost:9200/_snapshot/$SNAPSHOT_REPO?verify=true" -H 'Content-Type: application/json' \
	-d '{"type":"fs","settings":{"location":"/snapshots","compress":true}}'
log "repo '$SNAPSHOT_REPO' san sang (fs:/snapshots)"

# --- 1. Snapshot OpenSearch, tru logs/logs-* ----------------------------------
t0=$SECONDS
body=$(printf '{"indices":"%s","ignore_unavailable":true,"include_global_state":false,"metadata":{"taken_by":"deploy/backup.sh","git_sha":"%s"}}' \
	"$SNAPSHOT_INDICES" "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)")
result="$(os_curl -XPUT "localhost:9200/_snapshot/$SNAPSHOT_REPO/$snap?wait_for_completion=true" \
	-H 'Content-Type: application/json' -d "$body")"
state="$(json 'print(d.get("snapshot", {}).get("state", "ERROR"))' <<<"$result")"
[ "$state" = "SUCCESS" ] || die "snapshot $snap state=$state: $result"
indices="$(json 'print(",".join(sorted(d["snapshot"]["indices"])))' <<<"$result")"
case ",$indices," in
	*,logs,*|*,logs-*) die "snapshot $snap lai chua index log: $indices" ;;
esac
log "snapshot $snap SUCCESS trong $((SECONDS - t0))s, indices: $indices"

# --- 2. Tar volume clustering-data --------------------------------------------
volume=""
cid="$(docker compose ps -q clustering 2>/dev/null || true)"
if [ -n "$cid" ]; then
	volume="$(docker inspect "$cid" --format '{{range .Mounts}}{{if eq .Destination "/app/clustering/data"}}{{.Name}}{{end}}{{end}}')"
fi
if [ -z "$volume" ]; then
	volume="$(docker volume ls -q | grep -E '(^|_)clustering-data$' | head -1 || true)"
fi
[ -n "$volume" ] || die "khong tim thay volume clustering-data"
tarball="clustering-data-$stamp.tar.gz"
# Image caddy:2.8-alpine da co san tren VM (gateway) -> khong phai pull them.
docker run --rm -v "$volume:/data:ro" -v "$BACKUP_DIR/clustering-data:/out" caddy:2.8-alpine \
	sh -ec "tar czf /out/$tarball --exclude='./storm-*' --exclude='*.tmp' -C /data . && chown $(id -u):$(id -g) /out/$tarball"
log "tar volume $volume -> clustering-data/$tarball ($(du -h "$BACKUP_DIR/clustering-data/$tarball" | cut -f1))"

# --- 3. Xoa ban cu hon RETENTION_DAYS (bat buoc: snapshot chiem dia) ----------
old="$(os_curl "localhost:9200/_snapshot/$SNAPSHOT_REPO/_all" | RETENTION_DAYS="$RETENTION_DAYS" MIN_KEEP="$MIN_KEEP" json '
import os, time
cutoff = (time.time() - int(os.environ["RETENTION_DAYS"]) * 86400) * 1000
snaps = sorted(d["snapshots"], key=lambda s: s["start_time_in_millis"], reverse=True)
keep = int(os.environ["MIN_KEEP"])
for s in snaps[keep:]:
    if s["snapshot"].startswith("nightly-") and s["start_time_in_millis"] < cutoff:
        print(s["snapshot"])')"
for s in $old; do
	os_ack -XDELETE "localhost:9200/_snapshot/$SNAPSHOT_REPO/$s"
	log "xoa snapshot cu $s"
done
# Tar: cu hon RETENTION_DAYS ngay, nhung luon giu MIN_KEEP file moi nhat.
ls -1t "$BACKUP_DIR"/clustering-data/clustering-data-*.tar.gz 2>/dev/null | tail -n +"$((MIN_KEEP + 1))" | while read -r f; do
	if [ -n "$(find "$f" -mtime +"$((RETENTION_DAYS - 1))" -print)" ]; then
		rm -f "$f" && log "xoa tar cu $(basename "$f")"
	fi
done

# --- 4. Ghi danh sach snapshot (evidence) --------------------------------------
os_curl "localhost:9200/_snapshot/$SNAPSHOT_REPO/_all?pretty" > "$BACKUP_DIR/snapshot-list.json"
log "dung luong: $(du -sh "$BACKUP_DIR/os" | cut -f1) snapshot, $(du -sh "$BACKUP_DIR/clustering-data" | cut -f1) clustering-data"

# --- 5. Copy ra ngoai VM -------------------------------------------------------
if [ -n "$BACKUP_REMOTE" ]; then
	# Copy NGUYEN thu muc repo `os/`: repo fs la incremental, thieu file nao la
	# snapshot do hong. --delete de ben ngoai cung xoa theo retention.
	rsync -az --delete -e "ssh $BACKUP_SSH_OPTS" \
		--exclude '.backup.lock' --exclude 'backup.log' \
		"$BACKUP_DIR/" "$BACKUP_REMOTE/"
	log "rsync -> $BACKUP_REMOTE xong"
else
	log "CANH BAO: BACKUP_REMOTE trong -> ban backup CHI nam tren VM (mat VM la mat ca backup)." \
		"Keo ve may khac bang deploy/pull-backup.sh."
fi

log "xong $snap"
ping_hc ""
