#!/usr/bin/env bash
set -euo pipefail

ref="${1:-}"
if [ -z "$ref" ]; then
	echo "dung: deploy/deploy.sh <git-ref>" >&2
	echo "vd:   deploy/deploy.sh main        deploy/deploy.sh adf51a7" >&2
	exit 2
fi

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
	echo "that bai: co file da commit bi sua tay tren VM, commit hoac stash truoc khi deploy" >&2
	git status --short --untracked-files=no >&2
	exit 2
fi

git fetch --all --prune
target="$(git rev-parse --verify --quiet "origin/$ref" || git rev-parse --verify --quiet "$ref")" || {
	echo "that bai: khong tim thay ref '$ref'" >&2
	exit 2
}
git checkout --detach "$target"

GIT_SHA="$(git rev-parse --short HEAD)"
export GIT_SHA
echo "deploy '$ref' -> $GIT_SHA"

docker compose up -d --build ingestion demo-app clustering query-api gateway
docker compose restart gateway

addr="$(docker compose port query-api 8002)"
if [ -z "$addr" ]; then
	echo "that bai: query-api khong publish cong nao, xem docker compose ps" >&2
	exit 1
fi

got=""
deadline=$((SECONDS + 60))
while [ "$SECONDS" -lt "$deadline" ]; do
	got="$(curl -fsS "http://${addr}/health" 2>/dev/null | grep -o '"version":"[^"]*"' | cut -d'"' -f4 || true)"
	if [ "$got" = "$GIT_SHA" ]; then
		echo "ok: http://${addr}/health tra version=$got"
		exit 0
	fi
	sleep 3
done

echo "that bai: /health tra version='${got:-<khong doc duoc>}', can '$GIT_SHA'" >&2
echo "kiem tra: docker compose logs query-api --tail 50" >&2
exit 1
