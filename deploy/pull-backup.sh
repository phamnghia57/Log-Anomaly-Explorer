#!/usr/bin/env bash
# Keo ban backup tu VM ve may nay (phuong an 0 dong: copy ve may mot thanh vien).
# VM khong SSH nguoc vao laptop sau NAT duoc, nen may thanh vien chu dong keo.
#
#   deploy/pull-backup.sh <user>@<vm-ip> [duong-dan-repo-tren-vm] [thu-muc-dich]
#   vd: deploy/pull-backup.sh azureuser@20.1.2.3 prj2 ./backups
#
# Windows: chay trong WSL hoac Git Bash co rsync. Khong co rsync thi dung:
#   scp -r <user>@<vm-ip>:prj2/backups ./backups
# Lap lich (cron / Task Scheduler) chay sau gio backup tren VM (~19:17 UTC).
# Copy NGUYEN thu muc os/: repo snapshot "fs" la incremental, thieu file la hong.
set -euo pipefail

src_host="${1:?dung: $0 <user>@<vm> [repo-tren-vm] [dich]}"
src_repo="${2:-prj2}"
dest="${3:-./backups}"

mkdir -p "$dest"
if command -v rsync >/dev/null 2>&1; then
	rsync -az --delete --exclude '.backup.lock' "$src_host:$src_repo/backups/" "$dest/"
else
	scp -rp "$src_host:$src_repo/backups/." "$dest/"
fi

echo "== $(date -u +%Y-%m-%dT%H:%M:%SZ) ban copy ngoai VM tai $(cd "$dest" && pwd) =="
ls -la "$dest" "$dest/os" "$dest/clustering-data"
du -sh "$dest/os" "$dest/clustering-data"
