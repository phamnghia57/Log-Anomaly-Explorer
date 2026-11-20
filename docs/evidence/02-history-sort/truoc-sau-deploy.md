# #97 — trước/sau trên bản deploy thật

Đo trên VM `log-anomaly-vps` (23.98.41.222), ngày **2026-11-19**, quanh 16:40–16:50 UTC.
Bổ sung cho [README.md](README.md) (kiểm chứng storage ở máy local của Nam) phần còn thiếu:
bằng chứng **trên chính bản đang deploy**.

## Cách đo

Gọi trực tiếp hàm đang chạy bên trong container `query-api`, không qua HTTP:

```sh
docker compose exec -T query-api python -c "...OpenSearchStore().list_history(CID, since=<30 ngay>, limit=10)"
```

Lý do không đo qua `GET /clusters/{id}/history`: endpoint yêu cầu JWT admin, mà
`ADMIN_SEED_USERNAME`/`ADMIN_SEED_PASSWORD` trong `.env` trên VM đang để trống (login trả
401). Gọi thẳng hàm cho kết quả giống hệt endpoint — endpoint chỉ bọc thêm `since` mặc định
30 ngày và kiểm cluster tồn tại — và chứng minh được đúng code đang chạy trong image.

Cụm đo: `50bc2ae687c58466` — cụm có nhiều điểm history nhất (42 điểm), đã ngừng sinh điểm
mới từ 2026-11-14 nên dữ liệu không đổi giữa hai lần đo.

## Kết quả

| | Image | `limit=10` trả về | Chạm điểm mới nhất? |
|---|---|---|---|
| Trước | `c5a6b1d` | `2026-11-03T09:00` → `2026-11-05T05:25` | **Không** |
| Sau | `6d3e3bd` | `2026-11-05T18:16` → `2026-11-14T08:25` | **Có** |

Điểm mới nhất trong kho: `2026-11-14T08:25:00+00:00`. Tổng số điểm của cụm: 42.

Trước khi sửa, hỏi "10 điểm mới nhất" thì hệ thống trả về 10 điểm **cũ nhất**, dừng ở
`05/11` — tức **lệch 9 ngày** so với dữ liệu thật đang có. Sau khi sửa, kết quả kết thúc
đúng tại điểm mới nhất và vẫn theo thứ tự tăng dần (đúng contract "oldest first").

Mã nguồn của hàm lấy từ trong container ở cả hai thời điểm:
[truoc-deployed-list_history.txt](truoc-deployed-list_history.txt) (`sort: asc` + `size`)
và [sau-deployed-list_history.txt](sau-deployed-list_history.txt) (`sort: desc` + `reversed`).

## Giới hạn

- **Chưa có ảnh biểu đồ Incident View trước/sau.** Cụm lớn nhất chỉ có 42 điểm, nhỏ hơn
  `limit` mặc định của UI (100) và của AI Assistant (50), nên ở quy mô dữ liệu hiện tại bug
  **không biểu hiện trên UI** — biểu đồ trước và sau sẽ giống nhau. Bản sửa mang tính phòng
  ngừa: nó chỉ có tác dụng thấy được khi một cụm vượt 50/100 điểm (với `WINDOW_SECONDS=60`
  là khoảng 50–100 phút có lỗi liên tục).
- Tiêu chí "cụm > 100 điểm" của #97 vì vậy chưa kiểm được trên UI thật.
- Tiêu chí ảnh biểu đồ Incident View trước/sau (#118) đã được nhóm quyết định **bỏ**: dữ liệu
  hiện tại không có cụm nào đủ lớn để tạo khác biệt quan sát được trên biểu đồ, và nhóm không
  bơm thêm log giả chỉ để đạt mốc 100 điểm.
- `first_anomaly_after` **không** bị lỗi tương tự: nó dùng `size: 1` + `asc` có chủ đích để
  tìm lần tái phát ĐẦU TIÊN sau `resolved_at`. Không đổi hàm này.

## Xác nhận code mới chạy đúng trong production

Sau `deploy/deploy.sh main` (rollback point: `c5a6b1d`):

- `/health` → `version: 6d3e3bd`; `/clustering/health` → `status: ok`.
- Heartbeat có đủ field mới của #103: `cycle_seconds`, `logs_read`, `clusters_out`,
  `window_to` — xem `docs/evidence/07-worker-load/heartbeat-sau-deploy.json`. Migration
  mapping trên index `clusters-heartbeat` đã có sẵn chạy thành công (`PUT .../_mapping` 200).
- Retention của #109 chạy ở chu kỳ live đầu tiên: `deleted=0 cutoff=2026-10-20T16:43:36`
  — cutoff đúng 30 ngày, không có điểm nào quá hạn nên không mất dữ liệu; tổng số điểm
  `cluster-history` giữ nguyên 382 trước và sau deploy.
- Ping dead-man của #102 hoạt động: mỗi chu kỳ worker gọi Healthchecks và nhận `200 OK`.
- Không có traceback/exception nào trong log worker 20 phút sau deploy.
- `ANOMALY_THRESHOLD=3.0` đã vào **cả hai** service `clustering` và `query-api`.
