# Evidence Task 04 — snapshot OpenSearch hằng đêm và diễn tập restore

**Đo cái gì:** dữ liệu không tái tạo được (`users`, `clusters-incidents`, `cluster-history`,
`assistant-conversations`, `ml_templates.json`) có bản sao hằng đêm ở ngoài VM, và restore được
trên một máy khác trong bao lâu (RTO), mất tối đa bao nhiêu giờ dữ liệu (RPO).

**Trạng thái:** script và cấu hình đã có trong repo, **chưa chạy trên VM / chưa diễn tập**. Các ô
"điền" bên dưới chỉ được điền bằng số đo thật. Quy trình đầy đủ:
[runbook — Khi mất dữ liệu / restore](../../task/runbook.md#khi-mất-dữ-liệu--restore).

## Cấu hình

| Mục | Giá trị |
|---|---|
| Repo snapshot | `nightly`, kiểu `fs`, `path.repo=/snapshots` ← `./backups/os` trên VM |
| Pattern index | `*,-.*,-logs,-logs-*,-storm-*`, `include_global_state=false` |
| Lịch | cron `17 19 * * *` UTC (02:17 giờ VN) → `bash deploy/backup.sh` |
| Retention | xoá snapshot + tar cũ hơn 7 ngày, luôn giữ ≥ 2 bản mới nhất |
| Bản ngoài VM | điền: `BACKUP_REMOTE=…` **hoặc** `deploy/pull-backup.sh` về máy của … |

## Kết quả (điền sau khi chạy)

| Tiêu chí | Trạng thái | File chứng minh |
|---|---|---|
| `_snapshot/nightly/_all` có ≥ 2 snapshot ở 2 ngày khác nhau | điền | `snapshot-list.json` |
| `logs-*` / `logs` không nằm trong snapshot | điền | `snapshot-list.json` (trường `indices`), dòng `index log trong snapshot` trong `restore-log.txt` |
| Có bản copy ngoài VM | điền | `offsite-ls.txt` (output `ls -la` + `du -sh` trên máy đích) |
| Restore trên máy khác: đăng nhập bằng tài khoản cũ | điền | `restore-log.txt` (`POST /auth/login -> HTTP 200`), `incident-view-sau-restore.png` |
| Mở được `cluster_id` cũ với đúng trạng thái incident | điền | `restore-log.txt` (dòng `incident:`), `incident-view-sau-restore.png` |
| Dung lượng snapshot (giả định < 1 GB) | điền `du -sh backups/os` = … | `du-backups.txt` |

| Chỉ số | Giá trị đo được |
|---|---|
| **RTO** (tổng, từ dòng `RTO do duoc` trong `restore-log.txt`) | điền |
| trong đó: OpenSearch sẵn sàng / restore / query-api healthy | điền / điền / điền |
| **RPO** | điền (≤ 24 h trên VM; ngoài VM = 24 h + độ trễ lần kéo về) |
| Tuổi snapshot lúc diễn tập | điền (dòng "cách đây … giờ" trong `restore-log.txt`) |
| Máy diễn tập | điền (OS, CPU, RAM, Docker) |

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
