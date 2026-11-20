# PR #117 — actionable alert evidence

Unit regression: [pytest-clustering.txt](../pr117-review/pytest-clustering.txt).
Incident acknowledged trên OpenSearch thật:
[verify-live-history.txt](../02-history-sort/verify-live-history.txt).

Đã kiểm tra payload có signature/link URL-encode, thiếu base URL thì link null,
suppression cho acknowledged và fail-open có cảnh báo khi đọc incident gặp
StorageError. Không có email/Make.com thật trong các test này.

Trước khi nghiệm thu #101, người có quyền webhook cần lưu ảnh email trước/sau,
che thông tin riêng tư, và đếm số thao tác thực từ email đến stack trace.
`incident_url` đưa tới Incident View, không tự mở hộp thoại stack trace; số thao
tác còn phụ thuộc trạng thái đăng nhập và thao tác chọn log. Chưa đo thì không
tuyên bố email → stack trace chỉ còn một click.

Thông báo contract chuẩn bị tại
`docs/task/pr117-review/issue-101-comment.md`; cần nhóm xác nhận trước merge.

## Payload thật trên bản deploy (2026-11-20, Nghĩa đo)

[alert-payload-deploy.json](alert-payload-deploy.json) là **đúng** request body mà worker trên
bản deploy `f21d294` gửi cho webhook, không phải output của test.

**Cách đo mà không gửi email thật:** trỏ riêng container `clustering` vào một HTTP server tạm
chạy trong chính container đó, rồi tạo một bất thường thật:

```bash
cd ~/prj2
ALERT_WEBHOOK_URL=http://localhost:8099/hook \
  docker compose up -d --force-recreate --no-deps clustering
docker compose exec -d clustering python /tmp/webhook_capture.py   # ghi POST dau tien ra file
docker compose exec -T clustering python /tmp/make_anomaly.py 45   # 45 log ERROR, signature moi
# ... doi 1-2 chu ky ...
docker compose up -d --force-recreate --no-deps clustering          # tra webhook that
```

`.env` không bị sửa, Make.com không nhận gì, hộp thư nhóm không có email rác. Cụm sinh ra:
`37b7d10c238806e5`, score **45.0**.

### Kết quả

| Trường | Giá trị thật trên bản deploy |
|---|---|
| `incident_url` | `https://log-anomaly-explorer.vercel.app/clusters/37b7d10c238806e5` |
| `trace_id` | `01b1c7eda9684e89be51181af7bd4be8` (một trace thật trong cụm) |
| `signature` | có, đã chuẩn hoá |
| `score` / `count` / `window_to` | `45.0` / `1` / `2026-11-20T03:11:00+00:00` |
| `message` | 7 dòng, có cả `Incident:` và `Trace:` |

Tức `ALERT_WEB_BASE_URL` **đã được đặt đúng trên VM** và `incident_url` không còn `null` —
đây là điều kiện cần của tiêu chí "từ email tới stack trace trong ít thao tác" của #101.

## Email thật đã nhận (2026-11-20)

[email-alert-that.png](email-alert-that.png) — email báo động **thật** do Make.com gửi tới hộp thư
nhóm lúc **11:12 giờ VN (04:12:11 UTC)**, cho cụm `583498fff9a5c679`.

Nguồn gốc: 60 request `fault=downstream` được bơm lúc 04:11:57 trong khi đo #108 (xem
[measurement-nghia.md](../11-assistant-golden-set/measurement-nghia.md) mục 5). Đây là một alert
tự nhiên của hệ thống, không phải email dựng sẵn. Mốc gửi lấy từ
`clusters-alert-state/_doc/583498fff9a5c679` → `sent_at = 2026-11-20T04:12:11.888580+00:00`,
khớp với giờ hiển thị trong ảnh.

Email xác nhận Make.com **có** render đúng những trường mà payload mang sang:

| Trường | Hiển thị trong email |
|---|---|
| `service` | `Service: demo-web` |
| `cluster_id` | `Cluster: 583498fff9a5c679` |
| `score` | `Score: 60.0` |
| `signature` | `Signature: simulated downstream failure` |
| `incident_url` | `Incident: https://log-anomaly-explorer.vercel.app/clusters/583498fff9a5c679` — **link bấm được** |
| `first_seen` | `First seen: 2026-11-20T04:11:57.392818+00:00` |
| `trace_id` | `Trace: 00eef0e9760a02eeb14c27879c2e995f` |

Dòng người gửi/người nhận đã được **che** (email và MSSV của 4 thành viên); subject, mốc thời gian
và toàn bộ thân email giữ nguyên.

**Vẫn chưa đo:** số thao tác thật từ email → stack trace. Ảnh trên chứng minh link có trong email
và trỏ đúng cụm, nhưng **không** đếm số click: `incident_url` mở Incident View, không tự mở hộp
thoại stack trace, và số thao tác còn phụ thuộc trạng thái đăng nhập. Chưa đo thì không tuyên bố
"email → stack trace chỉ còn một click".
