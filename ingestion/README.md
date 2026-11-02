# ingestion — Minh

Nhận structured log từ demo-app, validate schema, ghi vào kho dữ liệu. Nền tảng để Clustering (Nam) và Search/Incident View (Nghĩa) đọc dữ liệu.

## Trách nhiệm

- [x] Chọn **OpenSearch**, cài đặt `OpenSearchLogStore` trong `src/storage.py` (`InMemoryLogStore` chỉ còn để dev/test)
- [x] Index cho `StructuredLog` (theo [`log-schema.json`](../docs/architect/contracts/log-schema.json)): index theo ngày `logs-YYYY.MM.DD`, mapping tường minh (`src/storage.py` → `LOG_MAPPING`), tự tạo lúc khởi động
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
| `logs-YYYY.MM.DD` | Log hợp lệ. `_id` = `log_id` trả về từ `/ingest`. `trace_id`, `service`, `level`… là `keyword`; `message`, `stack_trace` là `text` (full-text); `metadata` chỉ lưu, không index |
| `logs-quarantine` | Log sai schema: `received_at`, `errors`, `log` (payload gốc) |

`LogStore` (interface cho Nam/Nghĩa): `search`, `search_with_total`, `get_logs(log_ids)`, `write_log`, `write_quarantine`, `delete_older_than`.

### Biến môi trường

| Biến | Mặc định |
|---|---|
| `STORAGE_BACKEND` | `opensearch` (`memory` để dev/test) |
| `OPENSEARCH_URL` | `http://localhost:9200` |
| `OPENSEARCH_USER` / `OPENSEARCH_PASSWORD` | rỗng (không auth) |
| `OPENSEARCH_VERIFY_CERTS` | `false` |
| `LOG_INDEX` / `QUARANTINE_INDEX` | `logs` / `logs-quarantine` |
| `LOG_INDEX_DAILY` | `true` (đồng nhất trong cả 3 service) |
| `INGEST_RATE_LIMIT_RPS` | `100` request/giây/process; `0` = tắt |
| `INGEST_MAX_BATCH_SIZE` | `500` log/lần |
| `OPENSEARCH_SHARDS` / `OPENSEARCH_REPLICAS` | `1` / `0` |
| `RETENTION_DAYS` | `30` |
| `RETENTION_INTERVAL_SECONDS` | `3600` (`0` = tắt, dùng cron) |

## Chạy thử

```bash
cd ingestion
pip install -r requirements.txt
docker compose up -d          # OpenSearch local tại :9200
uvicorn src.main:app --reload --port 8000
```

Không có Docker: `STORAGE_BACKEND=memory uvicorn src.main:app --port 8000`.

Test: `pip install -r requirements-dev.txt && pytest tests`

Endpoint: `POST /ingest` (202/400/429/503), `POST /ingest/batch` (202/400/413/422/429/503), `GET /search` (`service`, `trace_id`, `level`, `q`, `from`, `to`, `limit`, `offset`; mặc định 24h gần nhất), `GET /health`.

```bash
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{
  "timestamp": "2026-10-01T09:00:00Z", "level": "ERROR", "service": "demo-web",
  "trace_id": "abc123", "span_id": "span1", "message": "Simulated failure"
}'
```

## Evidence sở hữu

**Load test tầng ingestion** — đo throughput (log/giây) và tỷ lệ lỗi khi tải tăng. Script đặt tại `../load-tests/`.

## Nâng cấp: batch, limiter, facets và retention theo ngày

`POST /ingest/batch` nhận **JSON array** tối đa `INGEST_MAX_BATCH_SIZE` phần tử, mỗi phần tử phải đúng `log-schema.json`. Ví dụ:

```bash
curl -i -X POST http://localhost:8000/ingest/batch \
  -H "Content-Type: application/json" -H "Idempotency-Key: demo-batch-001" \
  -d '[{"timestamp":"2026-11-02T07:00:00Z","level":"INFO","service":"demo-web","trace_id":"abc","span_id":"def","message":"start"},{"timestamp":"2026-11-02T07:01:00Z","level":"ERROR","service":"demo-web","trace_id":"abc","span_id":"def","message":"timeout"}]'
```

- Trả **202**: `{ "accepted": true, "count": 2, "log_ids": ["...", "..."] }`. OpenSearch ghi **một bulk request**, không gửi N lệnh index độc lập.
- **400** nếu danh sách rỗng hoặc có log sai schema: trả `invalid: [{index, details}]`, log sai vào quarantine, **không ghi log hợp lệ** trong batch này. **413** nếu quá nhiều phần tử; **422** nếu body không phải mảng object.
- **429** khi vượt ngưỡng rps, có `Retry-After: 1`. Áp dụng **cả** `/ingest` lẫn `/ingest/batch`; chia sẻ sliding-window limiter trên từng process, không phải limiter phân tán/áp theo client. Client cần backoff + jitter, giới hạn batch, không retry liên tục.
- **503** khi kho ghi thất bại. Bulk có thể đã ghi một phần trước khi thất bại. Gửi cùng `Idempotency-Key` và cùng danh sách/ thứ tự sẽ tạo lại cùng `_id`, giúp retry không nhân bản dữ liệu. **Một key chỉ dùng cho đúng một batch bất biến**; server chưa lưu ledger để phát hiện key tái sử dụng với payload khác. Với request không key, retry có thể sinh log trùng.

`GET /search?level=ERROR` hỗ trợ `level` exact keyword. Response giữ `total` và `results`, cộng `facets.timeline`, `facets.levels`, `facets.services`; histogram theo giờ (`fixed_interval=1h`). Query API cũng cung cấp các trường này cho frontend, các facet chỉ phản ánh tập log khớp filter hiện hành.

**Daily retention:** ghi theo timestamp UTC vào `logs-YYYY.MM.DD`; clustering và query-api đọc `logs,logs-????.??.??` để không bỏ sót index `logs` cũ. Scheduler xóa **cả index ngày** khi toàn bộ ngày đó cũ hơn cutoff (không xóa từng document). Vì không thể drop nửa index, ngày cũ có thể còn tối đa gần 24h sau cutoff trước khi được drop. `logs-quarantine` không bị tác động. Đổi `LOG_INDEX_DAILY` cần đồng bộ các service. Chỉ khi chủ động rollback `LOG_INDEX_DAILY=false`, retention mới dùng lại `delete_by_query` trên index đơn cũ.

**Lưu ý triển khai với dữ liệu cũ:** index `logs` (trước nâng cấp) tiếp tục đọc được nhưng **không tự xóa** trong daily retention, cũng không tự được migrate. Sao lưu và migrate tài liệu từ `logs` sang các index ngày theo `timestamp`, kiểm tra số lượng và ID trước khi xóa thủ công index legacy. Tuyệt đối không xóa `logs` khi chưa xác nhận. Khi rollback mode/index, cần đánh giá cả việc đọc dữ liệu mới.

**Giới hạn:** limiter tại một process, không giới hạn chung khi chạy nhiều worker/replica (cần Redis hoặc API gateway để làm distributed limit). InMemory store chỉ dành cho test/dev, không đáp ứng yêu cầu mất mạng 30 phút và recoverability.
