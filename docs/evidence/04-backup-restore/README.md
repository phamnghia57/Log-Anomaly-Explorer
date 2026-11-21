# Evidence Task 04 — snapshot OpenSearch hằng đêm và diễn tập restore

**Đo cái gì:** dữ liệu không tái tạo được (`users`, `clusters-incidents`, `cluster-history`,
`assistant-conversations`, `ml_templates.json`) có bản sao hằng đêm ở ngoài VM, và restore được
trên một máy khác trong bao lâu (RTO), mất tối đa bao nhiêu giờ dữ liệu (RPO).

Script và cấu hình đã có trong repo. Quy trình đầy đủ:
[runbook — Khi mất dữ liệu / restore](../../task/runbook.md#khi-mất-dữ-liệu--restore).

## Cấu hình

| Mục | Giá trị |
|---|---|
| Repo snapshot | `nightly`, kiểu `fs`, `path.repo=/snapshots` ← `./backups/os` trên VM |
| Pattern index | `*,-.*,-logs,-logs-*,-storm-*`, `include_global_state=false` |
| Lịch | cron `17 19 * * *` UTC (02:17 giờ VN) → `bash deploy/backup.sh` |
| Retention | xoá snapshot + tar cũ hơn 7 ngày, luôn giữ ≥ 2 bản mới nhất |
| Bản ngoài VM | `BACKUP_REMOTE` trong `deploy/backup.env`, hoặc `deploy/pull-backup.sh` từ máy thành viên |

## Cách tạo từng file

Trên VM:

```bash
bash deploy/backup.sh --list                 # sau >= 2 dem
docker compose exec -T opensearch curl -s 'localhost:9200/_snapshot/nightly/_all?pretty' \
  > docs/evidence/04-backup-restore/snapshot-list.json
du -sh backups/os backups/clustering-data > docs/evidence/04-backup-restore/du-backups.txt
tail -40 backups/backup.log > docs/evidence/04-backup-restore/backup-log-tail.txt   # che URL neu co
```

Trên máy đích (ngoài VM):

```bash
deploy/pull-backup.sh azureuser@<vm-ip> prj2 ./backups | tee docs/evidence/04-backup-restore/offsite-ls.txt
DRILL_USERNAME=<admin-cu> DRILL_CLUSTER_ID=<cluster_id-cu> deploy/restore-drill.sh   # ghi restore-log.txt
```

Ảnh: chạy web trỏ vào query-api diễn tập (`API_PROXY_TARGET=http://localhost:18002 npm run dev`),
đăng nhập, mở Incident View của cụm cũ, chụp `incident-view-sau-restore.png` (che thông tin riêng tư).

`restore-log.txt` không chứa mật khẩu (script đọc bằng `read -s`, không in token). Không commit
thư mục `backups/` (đã có trong `.gitignore`): nó chứa hash mật khẩu và dữ liệu thật.
