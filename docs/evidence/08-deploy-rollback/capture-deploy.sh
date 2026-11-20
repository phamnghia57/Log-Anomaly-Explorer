#!/usr/bin/env bash
# Evidence #104 (Task 08): mot lan deploy + mot lan rollback THAT tren VM, kem thoi gian.
#
# Dung: bash capture_deploy.sh <ref_moi> <sha_cu>
# Vi du: bash capture_deploy.sh main 6d3e3bd
#
# Khong dung `set -e`: can ghi lai ca exit code cua tung lan, ke ca khi that bai.
cd ~/prj2 || exit 2

new_ref="${1:-main}"
old_sha="${2:-}"
[ -z "$old_sha" ] && { echo "thieu sha cu"; exit 2; }
out=/tmp/deploy-rollback.txt
: > "$out"

run_step() {   # $1 = nhan, $2 = ref
	local label="$1" ref="$2" t0 t1 code
	t0="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
	local start_epoch=$SECONDS
	{
		echo "########################################################################"
		echo "# $label : deploy/deploy.sh $ref"
		echo "# bat dau : $t0"
	} >> "$out"
	bash deploy/deploy.sh "$ref" >> "$out" 2>&1
	code=$?
	t1="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
	{
		echo "# ket thuc: $t1"
		echo "# keo dai : $((SECONDS - start_epoch)) giay"
		echo "# exit    : $code"
		echo "# /health : $(curl -s localhost:9002/health)"
		echo "# /clustering/health: $(curl -s localhost:9002/clustering/health)"
		echo "# web_git_sha tren trang System Status lay tu /health o tren."
		echo
	} >> "$out"
	echo "$label -> exit=$code ($((SECONDS - start_epoch))s)"
	return $code
}

{
	echo "Evidence #104 - deploy va rollback that tren VM log-anomaly-vps (23.98.41.222)"
	echo "Chay luc: $(date -u '+%Y-%m-%dT%H:%M:%SZ') UTC"
	echo "Bat dau tu version: $(curl -s localhost:9002/health)"
	echo "Rollback point da ghi truoc: $old_sha"
	echo
} >> "$out"

run_step "LAN 1 - DEPLOY tien len" "$new_ref"
run_step "LAN 2 - ROLLBACK ve ban truoc" "$old_sha"
run_step "LAN 3 - DEPLOY lai ban moi (tra production ve dung trang thai)" "$new_ref"

{
	echo "########################################################################"
	echo "# Trang thai cuoi"
	echo "# $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
	echo "# /health            : $(curl -s localhost:9002/health)"
	echo "# /ingestion/health  : $(curl -s localhost:9002/ingestion/health)"
	echo "# /clustering/health : $(curl -s localhost:9002/clustering/health)"
	echo "# docker compose ps  :"
	docker compose ps --format '#   {{.Service}} {{.Status}}'
	echo "# grep -c ':latest' docker-compose.yml -> $(grep -c ':latest' docker-compose.yml)"
} >> "$out"

echo "=== da ghi $out ==="
tail -20 "$out"
