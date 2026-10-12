# demo-app — Mạnh

Ứng dụng demo (web, giả lập mobile qua API) đóng vai trò **nguồn log** cho Log Anomaly Explorer. Không phải sản phẩm chính — chỉ cần đủ để sinh structured log + trace thật và tạo được bất thường có kiểm soát.

## Trách nhiệm

- [x] Gắn OpenTelemetry SDK (`src/telemetry.py`) — sinh `trace_id`/`span_id` thật cho mỗi request
- [x] Hoàn thiện `emit_log()` trong `src/main.py` để dùng trace context thật thay vì placeholder
- [x] Thêm endpoint giả lập cho luồng mobile (`/api/mobile/items`)
- [x] Mở rộng fault injection cho web và mobile với value, connection, runtime

## Hợp đồng đang tuân theo

Mọi log gửi đi qua `POST {INGESTION_URL}/ingest` phải đúng [`docs/contracts/log-schema.json`](../docs/architect/contracts/log-schema.json).

## Chạy thử

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001
```

- `GET /api/items` — baseline web; hỗ trợ `fault`, `rate` và `seed`
- `GET /api/mobile/items` — baseline mobile-api; hỗ trợ `fault`, `rate` và `seed`
- `GET /simulate-error` — fault injection dùng chung; hỗ trợ `fault`, `rate`, `seed`

Các fault được hỗ trợ:

- `value` — dữ liệu nghiệp vụ không hợp lệ, trả HTTP 422.
- `connection` — kết nối downstream bị từ chối, trả HTTP 502.
- `runtime` — lỗi thực thi có kiểm soát, trả HTTP 500.
- `timeout` — timeout tương thích ngược, trả HTTP 504 và được gắn nhãn `runtime`.
- `downstream` — fault tương thích ngược, trả HTTP 500 và được gắn nhãn `runtime`.

`rate` nằm trong khoảng `0` đến `1`: `0` tắt fault, `1` luôn kích hoạt, giá trị giữa
hai mức này lấy mẫu theo xác suất. Dùng `seed` để tái lập một lần gọi trong test.
Không truyền `fault` thì endpoint item luôn là baseline. Mọi fault đều gửi log đúng
[`log-schema.json`](../docs/architect/contracts/log-schema.json); platform được ghi trong
`metadata.platform` và error type trong `metadata.error_type` (`baseline` cho request
không bị lỗi). Fault `connection` là lỗi kết nối được tạo trực tiếp trong app, không
phụ thuộc vào việc một cổng localhost cụ thể có đang mở hay không.

### Test API
Mở PowerShell khác:

Test API thông thường:
`Invoke-RestMethod http://127.0.0.1:8001/api/items`

Test mobile:
`Invoke-RestMethod http://127.0.0.1:8001/api/mobile/items`

Test sáu tổ hợp fault (HTTP 422/502/500):
`Invoke-WebRequest "http://127.0.0.1:8001/api/items?fault=value&rate=1&seed=1"`
`Invoke-WebRequest "http://127.0.0.1:8001/api/items?fault=connection&rate=1&seed=1"`
`Invoke-WebRequest "http://127.0.0.1:8001/api/items?fault=runtime&rate=1&seed=1"`
`Invoke-WebRequest "http://127.0.0.1:8001/api/mobile/items?fault=value&rate=1&seed=1"`
`Invoke-WebRequest "http://127.0.0.1:8001/api/mobile/items?fault=connection&rate=1&seed=1"`
`Invoke-WebRequest "http://127.0.0.1:8001/api/mobile/items?fault=runtime&rate=1&seed=1"`

Tắt fault và kiểm tra tương thích ngược:
`Invoke-RestMethod "http://127.0.0.1:8001/api/items?fault=runtime&rate=0"`
`Invoke-WebRequest "http://127.0.0.1:8001/simulate-error?rate=1&fault=timeout"`
`Invoke-WebRequest "http://127.0.0.1:8001/simulate-error?rate=1&fault=downstream"`

Để tạo labeled anomaly period, gửi baseline vài phút, bật một fault với `rate=1`
trong một khoảng thời gian cố định, sau đó tắt bằng `rate=0`. Lưu thời điểm bắt đầu/kết
thúc, endpoint, fault, rate và seed cùng trace IDs từ ingestion để dùng cho clustering.

### Coverage matrix

| Platform | value | connection | runtime |
|---|---|---|---|
| web | Tested: 422 | Tested: 502 | Tested: 500 |
| mobile-api | Tested: 422 | Tested: 502 | Tested: 500 |

Chạy test tự động từ thư mục `demo-app`:

`venv\Scripts\python.exe -m pytest -q`
## Evidence sở hữu

**Fault injection** — ghi lại rõ: cách bật/tắt, tham số điều khiển (`rate`), và log/script đã dùng để tạo ra các giai đoạn bất thường dùng cho `clustering/evaluation/labeled_incidents.json`.
