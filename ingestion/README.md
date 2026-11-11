# ingestion — Minh

Nhận structured log từ demo-app, validate schema, ghi vào kho dữ liệu. Nền tảng để Clustering (Nam) và Search/Incident View (Nghĩa) đọc dữ liệu.

## Trách nhiệm

- [x] Chọn **OpenSearch**, cài đặt `OpenSearchLogStore` trong `src/storage.py` (`InMemoryLogStore` chỉ còn để dev/test)
- [x] Index cho `StructuredLog` (theo [`log-schema.json`](../docs/architect/contracts/log-schema.json)): index `logs-YYYY.MM.DD` theo ngày UTC, mapping tường minh (`src/storage.py` → `LOG_MAPPING`), tự tạo khi ghi
- [x] Quarantine: index riêng `logs-quarantine` (`write_quarantine`), `POST /ingest` trả 400 theo api-contract
- [x] Retention: `src/retention.py` chạy nền định kỳ (`RETENTION_INTERVAL_SECONDS`) hoặc cron `python -m src.retention`; số ngày lấy từ `RETENTION_DAYS`, **không hardcode**
- [x] Viết load test tầng ingestion trong `../load-tests/` — kết quả đo thật: xem [`../load-tests/README.md`](../load-tests/README.md) mục "Kết quả đo được"

## Hợp đồng đang tuân theo

- Input: `POST /ingest` nhận log theo [`log-schema.json`](../docs/architect/contracts/log-schema.json)
- Output: phục vụ `search()` cho Nghĩa, phục vụ đọc log thô cho Nam (clustering đọc theo `log_ids`)
- Chi tiết request/response: [`api-contract.md`](../docs/architect/contracts/api-contract.md)

## Kho dữ liệu: OpenSearch

| Index | Nội dung |
|---|---|
| `logs-YYYY.MM.DD` | Log hợp lệ mới. `_id` = `log_id` trả về từ `/ingest`. `trace_id`, `service`, `level`… là `keyword`; `message`, `stack_trace` là `text` (full-text); `metadata` chỉ lưu, không index |
| `logs-quarantine` | Log sai schema: `received_at`, `errors`, `log` (payload gốc) |

`LogStore` (interface cho Nam/Nghĩa): `search`, `search_with_total`, `aggregate_logs`, `get_logs(log_ids)`, `write_log`, `write_logs_batch`, `write_quarantine`, `delete_older_than`.

### Biến môi trường

| Biến | Mặc định |
|---|---|
| `STORAGE_BACKEND` | `opensearch` (`memory` để dev/test) |
| `OPENSEARCH_URL` | `http://localhost:9200` |
| `OPENSEARCH_USER` / `OPENSEARCH_PASSWORD` | rỗng (không auth) |
| `OPENSEARCH_VERIFY_CERTS` | `false` |
| `LOG_INDEX` / `QUARANTINE_INDEX` | `logs` / `logs-quarantine` |
| `OPENSEARCH_SHARDS` / `OPENSEARCH_REPLICAS` | `1` / `0` |
| `RETENTION_DAYS` | `30` |
| `RETENTION_INTERVAL_SECONDS` | `3600` (`0` = tắt, dùng cron) |
| `INGEST_RATE_LIMIT_RPS` | `100` request/giây/process, chung `/ingest` và `/ingest/batch` |
| `INGEST_MAX_BATCH_SIZE` | `500` log/request |

## Chạy thử

```bash
cd ingestion
pip install -r requirements.txt
docker compose up -d          # OpenSearch local tại :9200
uvicorn src.main:app --reload --port 8000
```

Không có Docker: `STORAGE_BACKEND=memory uvicorn src.main:app --port 8000`.

Test: `pip install -r requirements-dev.txt && pytest tests`

Endpoint: `POST /ingest`, `POST /ingest/batch` (202 / 400 / 422 / 429 / 503), `GET /search` (`service`, `level`, `trace_id`, `q`, `from`, `to`, `limit`, `offset`; mặc định 24h gần nhất), `GET /search/aggregations`, `GET /health`.

### Batch ingest và rate limiting

`POST /ingest/batch`: body là **JSON array 1–500 structured logs** theo schema gốc (không thêm trường mới). Toàn bộ item được kiểm tra trước khi ghi. Chỉ cần một log không hợp lệ: **400**, các log sai được quarantine, **không ghi bất kỳ log hợp lệ nào trong batch đó**. Batch hợp lệ ghi bằng OpenSearch Bulk API, trả `202`:

```json
{"accepted": true, "accepted_count": 2, "log_ids": ["uuid-1", "uuid-2"]}
```

Bất kỳ endpoint ingest nào vượt quá `INGEST_RATE_LIMIT_RPS` đều trả **429** và `Retry-After: 1`. Limiter dùng sliding window, đồng bộ trong *một tiến trình*; nếu dùng nhiều worker/replica hoặc cần rate limit phân tán, phải bổ sung giới hạn tập trung tại API gateway/Redis. Khi OpenSearch Bulk API trả lỗi, có thể đã ghi một phần; retry không bảo đảm idempotency do UUID mới được sinh ở request mới. **Không retry tự động không kiểm soát**; ứng dụng gửi cần lưu dấu các ID/log và phối hợp nhóm để bổ sung idempotency key ở header nếu cần (không đổi schema).

Ví dụ PowerShell:

```powershell
$batch = @(
  @{timestamp='2026-11-02T00:00:00Z';level='INFO';service='demo-web';trace_id='t1';span_id='s1';message='start'},
  @{timestamp='2026-11-02T00:00:01Z';level='ERROR';service='demo-web';trace_id='t2';span_id='s2';message='timeout'}
)
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/ingest/batch' -ContentType 'application/json' -Body (ConvertTo-Json -InputObject $batch -Depth 6)
```

### Idempotency-Key (VT-014)

Gửi kèm header `Idempotency-Key` (1..128 ký tự `[A-Za-z0-9._:-]`) cho `/ingest` hoặc `/ingest/batch` để **retry an toàn**: cùng key + cùng payload → trả lại đúng response lần đầu (header `Idempotent-Replayed: true`), không ghi thêm; cùng key + payload khác → `409`. Không gửi header → hành vi cũ. Retry sau `503`/ghi một phần không còn tạo log trùng vì `log_id` được suy ra tất định từ key + payload. Chi tiết, giới hạn và cách chạy test: [`README_VT014.md`](README_VT014.md). Biến môi trường: `IDEMPOTENCY_TTL_SECONDS` (mặc định `86400`).

### Daily indices + retention và compatibility

- Từ bản cập nhật này, ghi theo **ngày UTC của `timestamp` trong log**, ví dụ `logs-2026.11.02`. Không ghi mới vào index đơn `logs`.
- Query API và clustering đọc đồng thời **legacy index `logs`** và các `logs-????.??.??`, loại trừ `logs-quarantine`. `get_logs` dùng truy vấn `_id` xuyên index thay cho `mget` một index.
- Retention chỉ **drop toàn bộ daily index có ngày nhỏ hơn ngày cutoff**; làm tròn theo ngày nên dữ liệu có thể được giữ lâu hơn cấu hình tối đa khoảng 1 ngày. Không dùng `delete_by_query` cho daily indices. Kết quả retention của OpenSearch là **số index đã drop**, không phải số document.
- **Không tự xoá legacy `logs`** để tránh mất dữ liệu. Dữ liệu cũ không được daily retention dọn dẹp; vận hành phải lên kế hoạch migrate/backup và dọn legacy index thủ công sau khi được trưởng nhóm phê duyệt.
- Tránh client phụ thuộc trực tiếp vào tên index `logs` mà không dùng `LogStore.read_indices`; xem thay đổi `clustering/src/storage.py`.

### Histogram & facets

`GET /search/aggregations` trả `histogram: [{time,count}]`, `levels: [{key,count}]`, `services: [{key,count}]`. Hỗ trợ `service`, `level`, `trace_id`, `q`, `from`, `to`, `interval=hour|day` (mặc định 24 giờ). Bản chính thức dùng `query-api` đã xác thực JWT admin để web gọi endpoint này.


```bash
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{
  "timestamp": "2026-10-01T09:00:00Z", "level": "ERROR", "service": "demo-web",
  "trace_id": "abc123", "span_id": "span1", "message": "Simulated failure"
}'
```

## Evidence sở hữu

**Load test tầng ingestion** — đo throughput (log/giây) và tỷ lệ lỗi khi tải tăng. Script đặt tại `../load-tests/`.
