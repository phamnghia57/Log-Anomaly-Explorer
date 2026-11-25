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

## Mốc thời gian lần đo 2026-11-16

| Mục | Giá trị |
|---|---|
| Period / Grace đã đặt trên Healthchecks | `5 phút / 3 phút` |
| Ping cuối cùng (giờ VN) | `09:52` — [stop-at.txt](stop-at.txt): `2026-11-16T02:52:40+00:00` |
| Nhận email "is DOWN" (giờ VN) | `10:00` — xem [email-down.png](email-down.png) |
| **Chênh lệch thật** | **`8 phút`** = Period 5 + Grace 3 |

## Kết quả

| Tiêu chí của Task 06 | Trạng thái |
|---|---|
| Ngừng ping → có email ≤ 10 phút | **đạt**, 8 phút thật (Period 5 + Grace 3) — xem `email-down.png`, mốc stop ở [stop-at.txt](stop-at.txt) |
| Ping lại → nhận email "recovered" | **đạt** — xem mục [Đo lại bằng worker thật](#đo-lại-bằng-worker-thật-2026-11-20) |
| `ALERT_WEBHOOK_URL` sai → nhận tín hiệu `fail` | **đạt** — [fail-signal.txt](fail-signal.txt), `GET <url>/fail → HTTP/1.1 200 OK` |
| `HEALTHCHECK_PING_URL` để trống → worker chạy bình thường | đạt ở phần cấu hình: biến mặc định rỗng, `docker compose config` pass; `ping()` trả về ngay khi biến rỗng (`clustering/src/healthcheck.py:12-14`) |

| File | Nội dung |
|---|---|
| `healthchecks-check.png` | Trang Healthchecks sau khi check chuyển DOWN |
| `email-down.png` | Email báo động nhận được |
| `stop-at.txt` | Mốc UTC lúc ngừng ping của lần đo 2026-11-16 |
| `fail-signal.txt` | Log worker của lần đo 2026-11-20: webhook sai → `/fail` 200 |

## Đo lại bằng worker thật (2026-11-20)

Lần đo 2026-11-16 ở trên dùng `curl` đóng vai worker. Lần này đo bằng **chính worker đang chạy
trên bản deploy**, với cả hai đường tín hiệu.

### Cách đo

```bash
cd ~/prj2
# 1. doi RIENG container clustering sang webhook sai (khong sua .env)
ALERT_WEBHOOK_URL=http://invalid.alert.test/hook \
  docker compose up -d --force-recreate --no-deps clustering
# 2. bom 60 log ERROR mot signature MOI vao dung mot cua so 60s -> score ~ 60, vuot nguong 3.0
docker compose exec -T clustering python /tmp/make_anomaly.py 60
# 3. doi vai chu ky roi doc log, 4. tra lai webhook that
docker compose up -d --force-recreate --no-deps clustering
```

Chỉ đổi biến cho **riêng container** `clustering`; `.env` không bị sửa, nên không có nguy cơ
quên trả lại. Cụm sinh ra: `dc59234a91502b5f`, service `alert-path-test`, score **60.0**,
status `anomalous`.

### Kết quả (mốc UTC lấy từ log container)

| Thời điểm | Sự kiện | Dòng log |
|---|---|---|
| 02:57:38 | đổi `clustering` sang webhook sai | — |
| 02:57:54 | bơm 60 log ERROR vào cửa sổ 02:57:00–02:58:00 | `ingest tra ve 202, accepted_count=60` |
| 02:58:10.092 | worker gửi digest → **thất bại** | `ERROR:clustering.alert:Alert digest failed` |
| 02:58:10.826 | worker gửi **tín hiệu `/fail`** → thành công | `GET https://hc-ping.com/<token>/fail "HTTP/1.1 200 OK"` |
| 02:59:10.755 | chu kỳ kế tiếp yên tĩnh → ping **thành công** trở lại | `GET https://hc-ping.com/<token> "HTTP/1.1 200 OK"` |
| 03:01:43 | trả `clustering` về webhook thật | — |

Phép đo này chứng minh thêm:

- **`/fail` tới được dịch vụ ngoài**: HTTP 200, không phải suy luận từ việc "không thấy lỗi".
- **Một lần gửi thất bại không làm worker im lặng mãi**: chu kỳ 02:59 ping lại bình thường. Đây
  đúng là lỗi mà bản sửa `delivery_failed = False` đầu mỗi chu kỳ (PR #117) vá — trước đó một lần
  webhook lỗi sẽ chặn mọi ping về sau và dead-man switch báo động giả vĩnh viễn.
- Vì `02:58:10` có `/fail` và `02:59:10` có ping thành công, Healthchecks chuyển **DOWN → UP**
  trong vòng 1 phút → dự kiến email "is DOWN"/"is UP" quanh 09:58–09:59 giờ VN. Email thật chụp
  được lại đến từ một lần `clustering` ngừng ping sau đó, trong lúc đo #108 (container bị dừng
  ~03:46–03:53 UTC = 10:46–10:53 giờ VN) — lúc đó Period trên Healthchecks đã đổi thành **1
  phút**, không còn 5/3 như lần đo 2026-11-16. Email "is UP (recovered)" thật nhận lúc **10:52
  giờ VN**, downtime 45 giây. Vẫn là bằng chứng hợp lệ cho tiêu chí "ping lại → nhận email
  recovered" (worker ngừng ping thật → email thật), chỉ khác mốc giờ so với dự đoán ở trên.

Ảnh hộp thư: [email-recovered.png](email-recovered.png) — cặp email "is DOWN" / "is UP
(recovered)" lúc **10:52 giờ VN**, Period 1 phút.

### Giới hạn

- 60 log tấn công của drill (service `alert-path-test`) **vẫn còn** trong index `logs-*`
  production; xoá bằng `delete_by_query` theo `service: alert-path-test` nếu muốn dọn trước demo.
- Bản deploy lúc đo (`6d3e3bd`) **chưa có** commit `48339f1`, nên log thô của container có chứa
  URL ping đầy đủ. File evidence này đã che token bằng `sed`; log thô trên VM sẽ sạch sau khi
  deploy bản có `48339f1`.
- Runbook đã có mục "Giám sát bên ngoài và dead-man switch" phân biệt 2 nguồn alert
  (`docs/task/runbook.md:316`) → việc số 4 của checklist cũ đã xong.
