# ingestion — Minh

Nhận structured log từ demo-app, validate schema, ghi vào kho dữ liệu. Nền tảng để Clustering (Nam) và Search/Incident View (Nghĩa) đọc dữ liệu.

## Trách nhiệm

- [ ] Chọn **một** trong Elasticsearch/OpenSearch hoặc ClickHouse, cài đặt `LogStore` thật trong `src/storage.py` (đang là `InMemoryLogStore` tạm thời)
- [ ] Thiết kế index/table cho `StructuredLog` (theo [`log-schema.json`](../docs/contracts/log-schema.json))
- [ ] Hoàn thiện quarantine: nơi lưu log sai schema (hiện chỉ lưu trong bộ nhớ, `write_quarantine`)
- [ ] Lên lịch chạy `src/retention.py` định kỳ (cron/scheduler) — số ngày lưu lấy từ biến môi trường `RETENTION_DAYS`, **không hardcode**
- [ ] Viết load test tầng ingestion trong `../load-tests/`

## Hợp đồng đang tuân theo

- Input: `POST /ingest` nhận log theo [`log-schema.json`](../docs/contracts/log-schema.json)
- Output: phục vụ `search()` cho Nghĩa, phục vụ đọc log thô cho Nam (clustering đọc theo `log_ids`)
- Chi tiết request/response: [`api-contract.md`](../docs/contracts/api-contract.md)

## Chạy thử

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
```

```bash
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{
  "timestamp": "2026-10-01T09:00:00Z", "level": "ERROR", "service": "demo-web",
  "trace_id": "abc123", "span_id": "span1", "message": "Simulated failure"
}'
```

## Evidence sở hữu

**Load test tầng ingestion** — đo throughput (log/giây) và tỷ lệ lỗi khi tải tăng. Script đặt tại `../load-tests/`.
