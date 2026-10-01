# query-api — Nghĩa (nhóm trưởng)

Search log + Incident View (chi tiết cụm + liên kết trace/request). Cũng là nơi tổng hợp tích hợp chung của cả nhóm.

## Trách nhiệm

- [ ] Nối `GET /search` sang `LogStore` thật của Minh (hiện là `NotImplementedError`)
- [ ] Nối `GET /clusters`, `GET /clusters/{id}` sang dữ liệu `ClusterRecord` thật của Nam (hiện là mock tĩnh)
- [ ] Điền đầy đủ `logs` trong response `/clusters/{id}` bằng cách tra `log_ids` → `LogStore` — đây chính là Incident View
- [ ] Giữ đồng bộ 3 hợp đồng trong `docs/contracts/` khi có thay đổi, thông báo cả nhóm
- [ ] Review PR của Mạnh/Minh/Nam, gỡ xung đột tích hợp
- [ ] Hoàn thiện `docs/runbook.md` và chạy load test end-to-end trong `../load-tests/`

## Hợp đồng đang tuân theo

[`api-contract.md`](../docs/contracts/api-contract.md) — phần "Query & Incident API".

## Chạy thử

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8002
```

## Evidence sở hữu

- **Runbook**: [`../docs/runbook.md`](../docs/runbook.md)
- **Load test end-to-end**: `../load-tests/` — mô phỏng tải thật qua toàn bộ pipeline (ingest → cluster → alert → query)
