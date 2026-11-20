# Evidence Task 08 — deploy/rollback theo SHA, ghim digest Jaeger

**Đo cái gì:** `deploy/deploy.sh` có thật sự chặn được bản deploy lệch SHA, và rollback về SHA cũ
có hoạt động.

| File | Đo ở đâu | Lúc nào | Trạng thái |
|---|---|---|---|
| `dryrun-local.txt` | Máy dev, `git`/`docker`/`curl` giả | 2026-11-16 | Đã có — 7 nhánh của script |
| `deploy-rollback-vm.txt` | Trên VM thật | 2026-11-20 | **Đã có** — 1 lần deploy + 1 lần rollback + 1 lần deploy lại |

## Kết quả trên VM thật (2026-11-20)

Chạy bằng [capture-deploy.sh](capture-deploy.sh) trên VM `log-anomaly-vps` (23.98.41.222).
Output đầy đủ (719 dòng, có cả log build) ở [deploy-rollback-vm.txt](deploy-rollback-vm.txt).

| Lần | Lệnh | Bắt đầu (UTC) | Kết thúc (UTC) | Kéo dài | `exit` | `/health` trả `version` |
|---|---|---|---|---|---|---|
| 1 — deploy tiến lên | `deploy/deploy.sh main` | 03:03:43 | 03:04:22 | **39 giây** | `0` | `f21d294` ✅ |
| 2 — **rollback** | `deploy/deploy.sh 6d3e3bd` | 03:04:22 | 03:04:58 | **36 giây** | `0` | `6d3e3bd` ✅ |
| 3 — deploy lại | `deploy/deploy.sh main` | 03:04:58 | 03:05:34 | **36 giây** | `0` | `f21d294` ✅ |

Tổng cộng **1 phút 51 giây** cho cả ba lần. Nhanh vì layer `pip install` đã có trong cache —
lần build nguội đầu tiên lâu hơn nhiều, nên vẫn giữ nguyên cảnh báo "deploy ngoài giờ demo".

### Đối chiếu tiêu chí nghiệm thu của Task 08

| Tiêu chí | Kết quả |
|---|---|
| `deploy.sh <sha-moi>` → `/health` trả đúng SHA đó | **đạt** — lần 1 và 3, `version=f21d294` |
| `deploy.sh <sha-cu>` → `version` về SHA cũ, UI hoạt động | **đạt** — lần 2, `version=6d3e3bd`; `/clustering/health` trả `status: ok` ngay sau đó |
| Trang System Status không báo lệch bản | **đạt** — `getDeployMismatch` so `WEB_GIT_SHA` của frontend với `version` của `/health`; sau cả ba lần `/health` đều khớp SHA vừa deploy |
| Script thoát mã khác 0 khi `/health` không khớp | **đạt ở local** — tình huống 3 trong `dryrun-local.txt`; chưa chạy lại trên VM vì phải build một image sai `GIT_SHA` có chủ đích |
| `docker-compose.yml` không còn tag `:latest` | **đạt** — `grep -c ':latest' docker-compose.yml` → `0` |

### Ghi chú

- `/ingestion/health` trả `{"detail":"Not Found"}` khi gọi trực tiếp `localhost:9002` — đúng,
  đường đó chỉ tồn tại **qua gateway** (xem `deploy/Caddyfile`), không phải route của query-api.
  Kiểm nó bằng `https://<domain>/ingestion/health`, không phải cổng 9002.
- Rollback **không** cần script riêng: `deploy.sh` nhận bất kỳ ref/SHA nào. Đúng như kế hoạch.
- Lần deploy này cũng là lần đưa commit `48339f1` (không log URL ping của Healthchecks) lên
  production. Kiểm lại sau 3 chu kỳ worker:
  `docker compose logs clustering --since 3m | grep -c "hc-ping"` → **0** (trước đó mỗi chu kỳ
  in một dòng chứa URL đầy đủ).
- Trace của Jaeger **không** mất khi deploy: `deploy.sh` không đụng service `jaeger`, và từ
  Task 10 span đã lưu trên đĩa bằng Badger thay vì RAM.

## Lệnh thu evidence trên VM (tái lập)

```bash
cd ~/prj2
bash docs/evidence/08-deploy-rollback/capture-deploy.sh main <sha-dang-chay-truoc-do>
# -> /tmp/deploy-rollback.txt
```

Script chạy ba lần theo thứ tự deploy → rollback → deploy lại, ghi mốc UTC bắt đầu/kết thúc,
thời lượng, `exit` và `/health` của **từng lần**, rồi in trạng thái cuối. Nó cố tình **không**
dùng `set -e` để còn ghi được exit code khi một lần thất bại.

Mong đợi: cả ba lần in `ok: http://127.0.0.1:9002/health tra version=<sha>` và thoát mã 0, với
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

Từ khi Task 10 chuyển Jaeger sang Badger (span lưu trên volume `jaeger-data`), recreate service
`jaeger` **không** còn mất trace. Cảnh báo "mất toàn bộ trace trong RAM" ở các bản trước của tài
liệu này không còn đúng.

**Kết luận trên VM:** `deploy/deploy.sh` chạy được cả hai chiều trên VM thật, mỗi lần dưới 40
giây với cache nóng, và tự kiểm `version` nên không thể deploy xong mà vẫn lệch bản. Rollback
dùng đúng script đó với SHA cũ — đã chạy thật một lần về `6d3e3bd` rồi tiến lại `f21d294`.
Bốn trong năm tiêu chí nghiệm thu đã đạt trên VM; tiêu chí "thoát mã khác 0" vẫn chỉ có bằng
chứng ở local (stub) vì muốn verify trên VM phải chủ ý build một image sai `GIT_SHA`.
