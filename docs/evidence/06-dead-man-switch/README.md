# Evidence Task 06 — dead-man switch cho worker clustering

**Đo cái gì:** worker ngừng ping thì sau bao lâu có email báo động, và tín hiệu đó có thật sự
tới hộp thư hay không.

**Vì sao cần:** `ALERT_WEBHOOK_URL` chỉ gửi email khi **có** bất thường. Khi chính worker chết —
hết quota, đĩa đầy, hoặc cả VM tắt — hệ thống im lặng, và người trực hiểu "không có email" là
"không có sự cố". Dead-man switch đảo ngược logic đó: im lặng chính là tín hiệu báo động.

## Cấu hình đo

- **Ngày đo:** 2026-11-16, từ máy dev (Windows) gọi tới Healthchecks.io.
- **Dịch vụ:** [Healthchecks.io](https://healthchecks.io), gói free. Check tên
  `clustering worker (prj2)`.
- **Cách đo:** dùng `curl` đóng vai worker. Phần code ping trong `clustering/src/worker.py` và
  `clustering/src/alert.py` thuộc PR của Nam, chưa merge tại thời điểm đo — nên lần đo này xác
  nhận **dịch vụ ngoài và đường email hoạt động đúng**, chưa xác nhận worker thật biết ping.
- **Biến môi trường:** `HEALTHCHECK_PING_URL` đã có trong `docker-compose.yml` (service
  `clustering`) và `.env.example` từ PR #111; để trống = tắt.

> Ping URL là secret dạng nhẹ: ai có nó đều ping thay worker được và làm dead-man switch im lặng
> vĩnh viễn. Không ghi URL vào file này, không để lộ trong ảnh chụp.

## CẦN ĐIỀN trước khi commit

| Mục | Giá trị |
|---|---|
| Period / Grace đã đặt trên Healthchecks | `5 phút / 3 phút` |
| Ping cuối cùng `(09:53)` | `5` |
| Nhận email "is DOWN" `(10:00)` | `3` |
| **Chênh lệch thật** | ** `1 phút` ** |

## Kết quả

| Tiêu chí của Task 06 | Trạng thái |
|---|---|
| Ngừng ping → có email ≤ 10 phút | **đạt**, `<N>` phút thật — xem `email-down.png` |
| Ping lại → nhận email "recovered" | chưa đo |
| `ALERT_WEBHOOK_URL` sai → nhận tín hiệu `fail` | chưa đo, cần `alert.py` của Nam |
| `HEALTHCHECK_PING_URL` để trống → worker chạy bình thường | đạt ở phần cấu hình: biến mặc định rỗng, `docker compose config` pass |

| File | Nội dung |
|---|---|
| `healthchecks-check.png` | Trang Healthchecks sau khi check chuyển DOWN |
| `email-down.png` | Email báo động nhận được |

## Còn lại để đóng Task 06

1. Nam merge phần ping trong `worker.py` + `/fail` trong `alert.py`.
2. Bỏ **Pause** cho check trên Healthchecks, đặt `HEALTHCHECK_PING_URL` vào `.env` trên VM rồi
   `docker compose up -d --force-recreate clustering`.
3. Đo lại bằng worker thật: `docker compose stop clustering` → đếm phút tới lúc email;
   `docker compose start clustering` → email "recovered".
4. Cập nhật `docs/task/runbook.md`: nguồn alert từ nay có 2 loại — anomaly từ worker, và
   uptime/dead-man từ dịch vụ ngoài — phân biệt để không xử lý nhầm.

Trong lúc chờ, check được đặt **Pause** để không gửi email báo động giả mỗi vài phút khi worker
chưa biết ping. Quên bước này thì cả nhóm sẽ học cách phớt lờ email báo động — đúng thói quen
nguy hiểm nhất với một hệ thống cảnh báo.
