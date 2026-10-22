# query-api — Nghĩa (nhóm trưởng)

Search log + Incident View (chi tiết cụm + liên kết trace/request). Cũng là nơi tổng hợp tích hợp chung của cả nhóm.

## Trách nhiệm

- [x] Nối `GET /search` sang `LogStore` thật của Minh (import thẳng `ingestion.src.storage`)
- [x] Nối `GET /clusters`, `GET /clusters/{id}` sang `ClusterRecord` thật của Nam (`clustering.src.storage.OpenSearchStore`)
- [x] Điền đầy đủ `logs` trong response `/clusters/{id}` bằng cách tra `log_ids` → `LogStore` — đây chính là Incident View
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

Endpoint:

| Endpoint | Tham số | Ghi chú |
|---|---|---|
| `GET /health` | — | `503 degraded` khi mất kết nối kho dữ liệu |
| `GET /search` | `service`, `trace_id`, `q`, `from`, `to`, `limit`, `offset` | Mặc định 24h gần nhất; `total` không bị cắt bởi `limit` |
| `GET /clusters` | `status`, `since`, `limit`, `offset` | Mặc định `since` theo `RETENTION_DAYS` |
| `GET /clusters/{id}` | — | Incident View: cụm + `logs` tra từ `log_ids` |

```bash
curl "http://localhost:8002/search?service=demo-web&q=timeout&limit=20"
curl "http://localhost:8002/clusters?status=alerted"
curl "http://localhost:8002/clusters/<cluster_id>"
```

**Lưu ý về `/clusters*`**: đọc cụm qua `clustering.src.storage.OpenSearchStore` (Nam), mà
lớp này **bắt buộc `STORAGE_BACKEND=opensearch`**. Khi chạy `STORAGE_BACKEND=memory`,
`/health` và `/search` vẫn hoạt động bình thường, riêng `/clusters*` trả `503` kèm lý do rõ
ràng — không làm sập cả service.

Test: `pip install -r query-api/requirements-dev.txt && cd query-api && pytest`

## Evidence sở hữu

- **Runbook**: [`../docs/task/runbook.md`](../docs/task/runbook.md)
- **Load test end-to-end**: `../load-tests/` — mô phỏng tải thật qua toàn bộ pipeline (ingest → cluster → alert → query)
