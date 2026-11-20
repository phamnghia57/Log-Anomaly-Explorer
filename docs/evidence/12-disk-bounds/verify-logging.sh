#!/usr/bin/env bash
# Evidence #109: xac minh logging driver da vao TUNG container sau khi deploy.
# Dung: bash verify_logging.sh
cd ~/prj2 || exit 2
out=/tmp/logconfig-sau.txt

{
	echo "# Evidence #109 - SAU khi dat logging driver"
	echo "# $(date -u '+%Y-%m-%dT%H:%M:%SZ') tren VM log-anomaly-vps"
	echo "# GIT_SHA deployed = $(curl -s localhost:9002/health | sed 's/.*"version":"\([^"]*\)".*/\1/')"
	echo "# HEAD cua repo tren VM = $(git rev-parse --short HEAD)"
	echo
	echo "## docker compose config - khoi logging sau khi mo rong anchor"
	docker compose config 2>/dev/null | grep -c 'driver: json-file' | sed 's/^/so service co driver json-file tuong minh: /'
	echo
	echo "## docker inspect LogConfig cua tung container (tieu chi nghiem thu)"
	fail=0
	for c in $(docker compose ps -q); do
		name="$(docker inspect --format '{{.Name}}' "$c")"
		cfg="$(docker inspect --format '{{json .HostConfig.LogConfig}}' "$c")"
		case "$cfg" in
			*'"max-size":"10m"'*) status="OK" ;;
			*) status="CHUA AP DUNG"; fail=1 ;;
		esac
		printf '%-24s %-14s %s\n' "$name" "$status" "$cfg"
	done
	echo
	echo "## Ket luan: $([ "$fail" -eq 0 ] && echo 'moi container da co max-size=10m max-file=3' || echo 'CON CONTAINER CHUA AP DUNG - can docker compose up -d cho ca stack')"
	echo
	echo "## Kich thuoc file log sau khi recreate"
	sudo du -sh /var/lib/docker/containers 2>/dev/null
	echo
	echo "## Jaeger dang chay dung image da ghim digest?"
	docker compose ps jaeger --format '{{.Image}}'
	echo "grep -c ':latest' docker-compose.yml -> $(grep -c ':latest' docker-compose.yml)"
	echo
	echo "## Health"
	echo "/health            : $(curl -s localhost:9002/health)"
	echo "/clustering/health : $(curl -s localhost:9002/clustering/health)"
} > "$out" 2>&1

cat "$out"
