# demo-app — Mạnh

Ứng dụng demo (web, giả lập mobile qua API) đóng vai trò **nguồn log** cho Log Anomaly Explorer. Không phải sản phẩm chính — chỉ cần đủ để sinh structured log + trace thật và tạo được bất thường có kiểm soát.

## Trách nhiệm

- [ ] Gắn OpenTelemetry SDK (`src/telemetry.py`) — sinh `trace_id`/`span_id` thật cho mỗi request
- [ ] Hoàn thiện `emit_log()` trong `src/main.py` để dùng trace context thật thay vì placeholder
- [ ] Thêm endpoint giả lập cho luồng mobile (hoặc gọi `/api/items` kèm header `X-Client: mobile` — tuỳ chọn, bàn với cả nhóm)
- [ ] Mở rộng `/simulate-error` nếu cần thêm loại lỗi khác (timeout, log sai schema) để phong phú dữ liệu fault injection

## Hợp đồng đang tuân theo

Mọi log gửi đi qua `POST {INGESTION_URL}/ingest` phải đúng [`docs/contracts/log-schema.json`](../docs/architect/contracts/log-schema.json).

## Chạy thử

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001
```

- `GET /api/items` — sinh log INFO bình thường (baseline)
- `GET /simulate-error?rate=0.3` — tiêm lỗi có xác suất `rate`, dùng để tạo giai đoạn bất thường có kiểm soát

## Evidence sở hữu

**Fault injection** — ghi lại rõ: cách bật/tắt, tham số điều khiển (`rate`), và log/script đã dùng để tạo ra các giai đoạn bất thường dùng cho `clustering/evaluation/labeled_incidents.json`.
