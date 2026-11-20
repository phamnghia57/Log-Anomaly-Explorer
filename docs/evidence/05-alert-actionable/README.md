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

**Vẫn chưa đo:** số thao tác thật từ email → stack trace. Phép đo này chỉ chứng minh payload
mang đủ thông tin và link trỏ đúng cụm; nó **không** chứng minh Make.com render link đó vào
email, cũng không đếm số click. Muốn đóng #101 vẫn cần ảnh một email thật và đếm thao tác tay.
