# query-api — Nghĩa (nhóm trưởng)

Search log + Incident View (chi tiết cụm + liên kết trace/request). Cũng là nơi tổng hợp tích hợp chung của cả nhóm.

## Trách nhiệm

- [x] Nối `GET /search` sang `LogStore` thật của Minh (import thẳng `ingestion.src.storage`)
- [ ] Nối `GET /clusters`, `GET /clusters/{id}` sang dữ liệu `ClusterRecord` thật của Nam (hiện là mock tĩnh) — **đang chờ** Nam bổ sung hàm đọc (`list_clusters`/`get_cluster`) vào `clustering/src/storage.py`
- [ ] Điền đầy đủ `logs` trong response `/clusters/{id}` bằng cách tra `log_ids` → `LogStore` — đây chính là Incident View
- [ ] Giữ đồng bộ 3 hợp đồng trong `docs/architect/contracts/` khi có thay đổi, thông báo cả nhóm
- [ ] Review PR của Mạnh/Minh/Nam, gỡ xung đột tích hợp
- [ ] Hoàn thiện `docs/task/runbook.md` và chạy load test end-to-end trong `../load-tests/`

## Hợp đồng đang tuân theo

[`api-contract.md`](../docs/architect/contracts/api-contract.md) — phần "Query & Incident API".

## Chạy thử

`query-api` import thẳng `ingestion.src.storage` (dùng chung một kho dữ liệu với Ingestion,
không gọi HTTP sang ingestion — giống cách clustering đọc log), nên **phải chạy từ thư mục
gốc repo**, không phải từ trong `query-api/`:

```bash
pip install -r query-api/requirements.txt
uvicorn query-api.src.main:app --reload --port 8002
```

Không có OpenSearch? Dùng backend nhẹ — **phải khớp với backend mà ingestion đang ghi vào**,
nếu không sẽ đọc một kho rỗng khác:

```bash
STORAGE_BACKEND=memory uvicorn query-api.src.main:app --reload --port 8002
```

Endpoint: `GET /health`, `GET /search` (`service`, `trace_id`, `q`, `from`, `to`, `limit`,
`offset`; mặc định 24h gần nhất, `total` không bị cắt bởi `limit`).

```bash
curl "http://localhost:8002/search?service=demo-web&q=timeout&limit=20"
```

Test: `pip install -r query-api/requirements-dev.txt && cd query-api && pytest`

## Evidence sở hữu

- **Runbook**: [`../docs/task/runbook.md`](../docs/task/runbook.md)
- **Load test end-to-end**: `../load-tests/` — mô phỏng tải thật qua toàn bộ pipeline (ingest → cluster → alert → query)
