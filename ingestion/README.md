# ingestion — Minh

Nhận structured log từ demo-app, validate schema, ghi vào kho dữ liệu. Nền tảng để Clustering (Nam) và Search/Incident View (Nghĩa) đọc dữ liệu.

## Trách nhiệm

- [x] Chọn **OpenSearch**, cài đặt `OpenSearchLogStore` trong `src/storage.py` (`InMemoryLogStore` chỉ còn để dev/test)
- [x] Index cho `StructuredLog` (theo [`log-schema.json`](../docs/architect/contracts/log-schema.json)): index `logs`, mapping tường minh (`src/storage.py` → `LOG_MAPPING`), tự tạo lúc khởi động
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
| `logs` | Log hợp lệ. `_id` = `log_id` trả về từ `/ingest`. `trace_id`, `service`, `level`… là `keyword`; `message`, `stack_trace` là `text` (full-text); `metadata` chỉ lưu, không index |
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

Endpoint: `POST /ingest` (202 / 400 / 503), `POST /ingest/bulk` (207, import hàng loạt — xem
[VT-016](../docs/task/evidence/vt-016/README.md)), `GET /search` (`service`, `trace_id`, `q`, `from`, `to`, `limit`, `offset`; mặc định 24h gần nhất), `GET /health`.

```bash
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{
  "timestamp": "2026-10-01T09:00:00Z", "level": "ERROR", "service": "demo-web",
  "trace_id": "abc123", "span_id": "span1", "message": "Simulated failure"
}'
```

## Evidence sở hữu

**Load test tầng ingestion** — đo throughput (log/giây) và tỷ lệ lỗi khi tải tăng. Script đặt tại `../load-tests/`.
