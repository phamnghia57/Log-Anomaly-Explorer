# Evidence Task 08 — deploy/rollback theo SHA, ghim digest Jaeger

**Đo cái gì:** `deploy/deploy.sh` có thật sự chặn được bản deploy lệch SHA, và rollback về SHA cũ
có hoạt động.

| File | Đo ở đâu | Lúc nào | Trạng thái |
|---|---|---|---|
| `dryrun-local.txt` | Máy dev, `git`/`docker`/`curl` giả | 2026-11-16 | Đã có — 7 nhánh của script |
| `deploy-vm.txt` | Trên VM | Sau merge | Nghĩa điền |
| `rollback-vm.txt` | Trên VM | Sau merge | Nghĩa điền |

## Lệnh thu evidence trên VM

Ghi lại **thời gian** mỗi lần, vì kế hoạch yêu cầu số đó:

```bash
cd ~/prj2
{ date -Is; time ./deploy/deploy.sh main; date -Is; } 2>&1 | tee docs/evidence/08-deploy-rollback/deploy-vm.txt
{ date -Is; time ./deploy/deploy.sh <sha-truoc-do>; date -Is; } 2>&1 | tee docs/evidence/08-deploy-rollback/rollback-vm.txt
./deploy/deploy.sh main        # quay lai ban moi nhat sau khi thu rollback
```

Mong đợi: cả hai lần in `ok: http://127.0.0.1:9002/health tra version=<sha>` và thoát mã 0, với
`<sha>` đúng bằng SHA được truyền vào. Trang **Trạng thái hệ thống** của web không báo lệch bản.

## Kiểm tra script thoát mã khác 0 khi lệch bản

Tiêu chí này đã verify ở local bằng stub (tình huống 3 trong `dryrun-local.txt`). Muốn verify trên
VM thì cách rẻ nhất là build query-api **không** truyền `GIT_SHA` rồi chạy script:

```bash
docker compose build --build-arg GIT_SHA=sai-co-y query-api
docker compose up -d --force-recreate query-api
./deploy/deploy.sh main ; echo "exit=$?"     # mong doi: exit=1 va in ro version lech
```

Chạy xong thì `./deploy/deploy.sh main` một lần nữa để trả lại trạng thái đúng.

## Áp digest Jaeger (một lần, sau merge)

`deploy.sh` **không** đụng `jaeger` để deploy thường không xoá trace. Nên lần đầu phải áp tay:

```bash
docker compose up -d jaeger
docker compose ps jaeger       # mong doi: image hien 1.76.0@sha256:ab6f...
```

Lần này **mất toàn bộ trace đang có trong RAM** — chọn lúc không ai đang điều tra.

**Kết luận trên VM:** _(điền sau khi có deploy-vm.txt)_
