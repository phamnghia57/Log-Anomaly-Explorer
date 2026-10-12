# demo-app — Mạnh

Ứng dụng demo (web, giả lập mobile qua API) đóng vai trò **nguồn log** cho Log Anomaly Explorer. Không phải sản phẩm chính — chỉ cần đủ để sinh structured log + trace thật và tạo được bất thường có kiểm soát.

## Trách nhiệm

- [x] Gắn OpenTelemetry SDK (`src/telemetry.py`) — sinh `trace_id`/`span_id` thật cho mỗi request
- [x] Hoàn thiện `emit_log()` trong `src/main.py` để dùng trace context thật thay vì placeholder
- [x] Thêm endpoint giả lập cho luồng mobile (`/api/mobile/items`)
- [x] Mở rộng `/simulate-error` với fault downstream và timeout có kiểm soát

## Hợp đồng đang tuân theo

Mọi log gửi đi qua `POST {INGESTION_URL}/ingest` phải đúng [`docs/contracts/log-schema.json`](../docs/architect/contracts/log-schema.json).

## Chạy thử

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001
```

- `GET /api/items` — sinh log INFO bình thường (baseline)
- `GET /api/mobile/items` — mô phỏng client mobile, sinh log INFO bình thường
- `GET /simulate-error?rate=0.3` — tiêm lỗi downstream với xác suất `rate`
- `GET /simulate-error?rate=1&fault=timeout` — mô phỏng downstream timeout, trả HTTP 504

`rate` nên nằm trong khoảng `0` đến `1`. Các fault injection đều gửi log đúng schema;
không cố tình gửi log sai schema từ demo-app vì ingestion phải nhận dữ liệu hợp lệ theo hợp đồng.

### Test API
Mở PowerShell khác:

Test API thông thường:
`Invoke-RestMethod http://127.0.0.1:8001/api/items`

Test mobile:
`Invoke-RestMethod http://127.0.0.1:8001/api/mobile/items`

Test lỗi downstream chắc chắn xảy ra:
`Invoke-WebRequest "http://127.0.0.1:8001/simulate-error?rate=1&fault=downstream"`

Test timeout:
`Invoke-WebRequest "http://127.0.0.1:8001/simulate-error?rate=1&fault=timeout"`

Test lỗi ngẫu nhiên 30%:
`Invoke-WebRequest "http://127.0.0.1:8001/simulate-error?rate=0.3&fault=downstream"`
## Evidence sở hữu

**Fault injection** — ghi lại rõ: cách bật/tắt, tham số điều khiển (`rate`), và log/script đã dùng để tạo ra các giai đoạn bất thường dùng cho `clustering/evaluation/labeled_incidents.json`.
