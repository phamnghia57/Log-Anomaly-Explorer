#!/usr/bin/env bash
# Do cycle_seconds cua clustering worker duoi error storm (issue #103) tren VM deploy,
# voi index RIENG (storm-*) thay vi dung stack thu hai (VM 4 GB khong du 2 OpenSearch).
#
# Chay tu thu muc goc repo tren VM (vd. ~/prj2):
#   load-tests/run_worker_storm.sh run 10      # lan luot 10, 50, 100
#   load-tests/run_worker_storm.sh run 50
#   load-tests/run_worker_storm.sh run 100
#   load-tests/run_worker_storm.sh restore     # BAT BUOC sau khi xong (ca khi bi Ctrl-C)
#   load-tests/run_worker_storm.sh summary     # dien bang vao load-tests/README.md
#
# Moi lan `run`:
#   1. dung ingestion + clustering, xoa index storm-* cu (moi muc tai doc lap),
#   2. bat lai 2 service tro vao storm-logs / storm-clusters / storm-cluster-history,
#      tat webhook + Healthchecks ping, state TF-IDF rieng (khong lam ban state that),
#   3. nap truoc PREFILL_MINUTES phut baseline (mac dinh 30 = HISTORY_WINDOWS),
#   4. collector (trong compose network, mount load-tests) + docker stats + Locust,
#   5. luu log worker, metadata may do.
#
# Bien moi truong tuy chon:
#   EVIDENCE_DIR      (docs/evidence/07-worker-load)
#   INGESTION_HOST    (http://localhost:<INGESTION_PORT trong .env, mac dinh 9000>)
#   LOCUST_BIN        (~/locust/bin/locust)
#   DURATION_SECONDS  (300)    thoi gian Locust; collector chay them 60 giay
#   PREFILL_MINUTES   (30)     0 = khong nap baseline (ghi ro trong README)
#   ERROR_STORM_SEED  (98)
#   LOCUST_USERS      (10->1, 50->2, 100->4)  moi user nham RATE/LOCUST_USERS req/s
#   STORM_INGEST_RATE_LIMIT  (max(100, 2*RATE)) gioi han ingest CHI trong luc do
#   YES=1             bo qua cau hoi xac nhan da pause uptime check
#   FORCE=1           cho phep ghi de evidence cua muc tai da co
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f docker-compose.yml ] || { echo "phai chay tu goc repo" >&2; exit 2; }

EVIDENCE_DIR="${EVIDENCE_DIR:-docs/evidence/07-worker-load}"
port_from_env() { [ -f .env ] && grep -E '^INGESTION_PORT=' .env | tail -1 | cut -d= -f2 | tr -d '"'"'"' ' || true; }
INGESTION_HOST="${INGESTION_HOST:-http://localhost:$(p=$(port_from_env); echo "${p:-9000}")}"
LOCUST_BIN="${LOCUST_BIN:-$HOME/locust/bin/locust}"
DURATION_SECONDS="${DURATION_SECONDS:-300}"
PREFILL_MINUTES="${PREFILL_MINUTES:-30}"
ERROR_STORM_SEED="${ERROR_STORM_SEED:-98}"
STORM_ENV_KEYS="LOG_INDEX CLUSTER_INDEX HISTORY_INDEX ML_STATE_PATH INGEST_RATE_LIMIT_RPS ALERT_WEBHOOK_URL HEALTHCHECK_PING_URL"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
os_curl() { docker compose exec -T opensearch curl -sS "$@"; }
svc_env() { docker compose exec -T "$1" printenv "$2" 2>/dev/null | tr -d '\r' || true; }

wait_ingestion() {
	for _ in $(seq 1 60); do
		curl -fsS "$INGESTION_HOST/health" >/dev/null 2>&1 && return 0
		sleep 2
	done
	echo "ingestion khong len o $INGESTION_HOST/health" >&2
	exit 1
}

confirm_monitors() {
	[ "${YES:-}" = "1" ] && return 0
	read -r -p "Da PAUSE check Healthchecks + UptimeRobot va khong sat gio demo? [y/N] " ans
	[ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "huy"; exit 1; }
}

cmd_run() {
	local rate="${1:-}"
	case "$rate" in 10|50|100) ;; *) echo "dung: $0 run 10|50|100" >&2; exit 2;; esac
	local users per_user limit
	case "$rate" in 10) users=1;; 50) users=2;; 100) users=4;; esac
	users="${LOCUST_USERS:-$users}"
	per_user="$(python3 -c "print(round($rate / $users, 3))")"
	limit="${STORM_INGEST_RATE_LIMIT:-$(( rate * 2 > 100 ? rate * 2 : 100 ))}"

	[ -x "$LOCUST_BIN" ] || { echo "khong thay $LOCUST_BIN - xem load-tests/README.md (tao venv ~/locust)" >&2; exit 2; }
	mkdir -p "$EVIDENCE_DIR"
	local evidence_abs; evidence_abs="$(cd "$EVIDENCE_DIR" && pwd)"
	for f in "cycle-$rate.csv" "storm-${rate}_stats.csv" "docker-stats-$rate.txt" "worker-$rate.log"; do
		if [ -e "$EVIDENCE_DIR/$f" ] && [ "${FORCE:-}" != "1" ]; then
			echo "$EVIDENCE_DIR/$f da ton tai; dat FORCE=1 de ghi de" >&2; exit 2
		fi
	done
	[ "${FORCE:-}" = "1" ] && rm -f "$EVIDENCE_DIR"/{cycle-$rate.csv,storm-${rate}_*.csv,docker-stats-$rate.txt,worker-$rate.log,locust-$rate.txt,prefill-$rate.json,run-$rate.json}

	confirm_monitors
	log "RATE=$rate users=$users x ${per_user} req/s, INGEST_RATE_LIMIT_RPS=$limit, prefill=${PREFILL_MINUTES}m, seed=$ERROR_STORM_SEED"

	log "dung ingestion + clustering, xoa index storm-* cu"
	docker compose stop ingestion clustering
	os_curl -XDELETE 'localhost:9200/storm-*?expand_wildcards=all' >/dev/null || true
	echo

	log "bat ingestion + clustering voi index storm-*"
	LOG_INDEX=storm-logs CLUSTER_INDEX=storm-clusters HISTORY_INDEX=storm-cluster-history \
	ALERT_WEBHOOK_URL= HEALTHCHECK_PING_URL= INGEST_RATE_LIMIT_RPS="$limit" \
	ML_STATE_PATH="clustering/data/storm-ml_templates-$rate.json" \
		docker compose up -d --no-deps --force-recreate ingestion clustering
	wait_ingestion
	[ "$(svc_env clustering CLUSTER_INDEX)" = "storm-clusters" ] \
		|| { echo "clustering KHONG chay voi storm-clusters - dung lai" >&2; exit 1; }
	[ -z "$(svc_env clustering ALERT_WEBHOOK_URL)" ] && [ -z "$(svc_env clustering HEALTHCHECK_PING_URL)" ] \
		|| { echo "webhook/healthcheck ping chua tat - dung lai" >&2; exit 1; }
	# Xoa state TF-IDF storm cua lan truoc (neu co) truoc khi worker kip ghi nhieu.
	docker compose exec -T clustering rm -f "clustering/data/storm-ml_templates-$rate.json" || true
	docker compose restart clustering >/dev/null

	local t0; t0="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	if [ "$PREFILL_MINUTES" -gt 0 ]; then
		log "nap truoc ${PREFILL_MINUTES} phut baseline"
		python3 load-tests/prefill_error_storm.py --rate "$rate" --minutes "$PREFILL_MINUTES" \
			--host "$INGESTION_HOST" --seed "$ERROR_STORM_SEED" --report "$EVIDENCE_DIR/prefill-$rate.json"
	fi

	log "collector ($((DURATION_SECONDS + 60)) s) trong compose network"
	docker compose run --rm --no-deps -T --user "$(id -u):$(id -g)" \
		-e CLUSTER_INDEX=storm-clusters -e OPENSEARCH_URL=http://opensearch:9200 \
		-v "$PWD/load-tests:/app/load-tests:ro" \
		-v "$evidence_abs:/out" \
		--entrypoint python query-api load-tests/capture_worker_cycles.py \
		--rate "$rate" --seconds "$((DURATION_SECONDS + 60))" --output "/out/cycle-$rate.csv" </dev/null &
	local collector=$!

	(
		while kill -0 "$collector" 2>/dev/null; do
			echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
			docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}'
			sleep 5
		done
	) > "$EVIDENCE_DIR/docker-stats-$rate.txt" &
	local stats=$!
	trap 'kill "$collector" "$stats" 2>/dev/null || true' INT TERM

	sleep 5
	log "Locust ${DURATION_SECONDS}s -> $INGESTION_HOST"
	LOAD_TEST_ERROR_STORM=true ERROR_STORM_RPS="$per_user" ERROR_STORM_SEED="$ERROR_STORM_SEED" \
	INGESTION_HOST="$INGESTION_HOST" \
		"$LOCUST_BIN" -f load-tests/locustfile.py ErrorStormUser --headless \
		-u "$users" -r "$users" -t "${DURATION_SECONDS}s" --csv "$EVIDENCE_DIR/storm-$rate" \
		2>&1 | tee "$EVIDENCE_DIR/locust-$rate.txt" || true

	log "cho collector ket thuc"
	wait "$collector" || echo "collector thoat ma khac 0, kiem tra $EVIDENCE_DIR/cycle-$rate.csv" >&2
	wait "$stats" 2>/dev/null || true
	trap - INT TERM

	docker compose logs clustering --since "$t0" --no-log-prefix > "$EVIDENCE_DIR/worker-$rate.log" 2>&1 || true
	rm -f "$EVIDENCE_DIR/storm-${rate}_stats_history.csv"   # vai MB, khong can cho bang

	RATE="$rate" USERS="$users" PER_USER="$per_user" LIMIT="$limit" T0="$t0" \
	PREFILL="$PREFILL_MINUTES" SEED="$ERROR_STORM_SEED" DURATION="$DURATION_SECONDS" \
	GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
	HEAP="$(docker compose exec -T opensearch printenv OPENSEARCH_JAVA_OPTS 2>/dev/null || true)" \
	python3 - "$EVIDENCE_DIR/run-$rate.json" <<'PY'
import json, os, platform, subprocess, sys
def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""
meta = {
    "rate": int(os.environ["RATE"]), "started_at": os.environ["T0"],
    "duration_seconds": int(os.environ["DURATION"]), "locust_users": int(os.environ["USERS"]),
    "per_user_rps": float(os.environ["PER_USER"]), "ingest_rate_limit_rps": int(os.environ["LIMIT"]),
    "prefill_minutes": int(os.environ["PREFILL"]), "seed": int(os.environ["SEED"]),
    "git_sha": os.environ["GIT_SHA"], "opensearch_heap": os.environ.get("HEAP", ""),
    "nproc": sh("nproc"), "mem_total": sh("free -h | awk '/^Mem:/{print $2}'"),
    "cpu_model": sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip(),
    "kernel": platform.release(), "history_windows": 30, "window_seconds": 60,
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2)
    fh.write("\n")
PY
	log "xong RATE=$rate. File trong $EVIDENCE_DIR:"
	ls -la "$EVIDENCE_DIR" | grep -E "(-|_)$rate(\.|_)" || true
	echo
	echo "Kiem tra trong locust-$rate.txt: so request, 'Expected 202; got 429', req/s thuc te."
	echo "Chay muc tiep theo, hoac: $0 restore"
}

cmd_restore() {
	log "khoi phuc cau hinh that cho ingestion + clustering (doc lai .env)"
	# shellcheck disable=SC2086
	unset $STORM_ENV_KEYS
	docker compose up -d --no-deps --force-recreate ingestion clustering
	wait_ingestion
	[ "$(svc_env clustering CLUSTER_INDEX)" = "clusters" ] \
		|| echo "CANH BAO: clustering khong chay voi CLUSTER_INDEX=clusters, kiem tra .env" >&2
	log "xoa index storm-* va state TF-IDF storm"
	os_curl -XDELETE 'localhost:9200/storm-*?expand_wildcards=all'; echo
	docker compose exec -T clustering sh -c 'rm -f clustering/data/storm-ml_templates-*.json' || true
	os_curl 'localhost:9200/_cat/indices/storm-*?v' || true
	echo
	log "da khoi phuc. CON PHAI: resume check Healthchecks + UptimeRobot, sau ~2 phut kiem tra"
	echo "  docker compose logs clustering --tail 5   # phai thay 'Processed ...' moi"
}

cmd_summary() {
	python3 load-tests/summarize_worker_cycles.py --evidence "$EVIDENCE_DIR" --update-readme load-tests/README.md
}

case "${1:-}" in
	run) shift; cmd_run "$@" ;;
	restore) cmd_restore ;;
	summary) cmd_summary ;;
	*) sed -n '2,12p' "$0"; exit 2 ;;
esac
