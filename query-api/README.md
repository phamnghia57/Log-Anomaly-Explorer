# query-api — Nghĩa (nhóm trưởng)

Search log + Incident View (chi tiết cụm + liên kết trace/request). Cũng là nơi tổng hợp tích hợp chung của cả nhóm.

## Trách nhiệm

- [x] Nối `GET /search` sang `LogStore` thật của Minh (import thẳng `ingestion.src.storage`)
- [x] Nối `GET /clusters`, `GET /clusters/{id}` sang `ClusterRecord` thật của Nam (`clustering.src.storage.OpenSearchStore`)
- [x] Điền đầy đủ `logs` trong response `/clusters/{id}` bằng cách tra `log_ids` → `LogStore` — đây chính là Incident View
- [ ] Giữ đồng bộ 3 hợp đồng trong `docs/architect/contracts/` khi có thay đổi, thông báo cả nhóm
- [x] Review PR của Mạnh/Minh/Nam, gỡ xung đột tích hợp
- [x] Hoàn thiện `docs/task/runbook.md` và chạy load test end-to-end trong `../load-tests/`

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
| `GET /clusters/{id}` | `logs_limit`, `logs_offset` | Incident View: cụm + `logs` tra từ `log_ids`, **có phân trang** (`logs_total` = tổng số log của cụm) |
| `GET /clusters/{id}/history` | `since`, `limit` | Xu hướng anomaly score theo thời gian (index `cluster-history`) |
| `GET /metrics` | — | Metrics dạng Prometheus, **không** route ra Internet qua gateway |
| `GET /assistant/clusters/{id}/conversation` | — | Hội thoại điều tra với AI Assistant (xem mục riêng bên dưới) |
| `POST /assistant/clusters/{id}/conversation/messages` | body `{"message": "..."}` | Gửi câu hỏi cho AI Assistant |

```bash
curl "http://localhost:8002/search?service=demo-web&q=timeout&limit=20"
curl "http://localhost:8002/clusters?status=alerted"
curl "http://localhost:8002/clusters/<cluster_id>?logs_limit=50"
curl "http://localhost:8002/clusters/<cluster_id>/history"
curl "http://localhost:8002/metrics"
```

## Observability của chính query-api

Không chỉ *hiển thị* dữ liệu quan sát, service này cũng **tự được quan sát** — đủ cả 3 pillar:

| Pillar | Ở đâu |
|---|---|
| Logs | OpenSearch (của Minh) |
| Traces | Jaeger — `src/telemetry.py` tạo span cho mỗi request (bỏ qua `/health`, `/metrics`) |
| Metrics | `GET /metrics` — bộ số RED: `http_requests_total`, `http_request_duration_seconds` |

Trace chỉ được gửi đi khi có `OTEL_EXPORTER_OTLP_ENDPOINT` (trong Docker Compose đã trỏ sẵn
sang `http://jaeger:4318`). Không đặt biến này thì service chạy bình thường, chỉ là không gửi
span — Jaeger chết cũng **không** làm service lỗi (chỉ log `Failed to export spans batch`).

Dùng để làm gì: load test đo được `GET /clusters/{id}` là endpoint chậm nhất (median 530ms,
p99 1.7s — xem [`../load-tests/README.md`](../load-tests/README.md)). Có trace + metrics thì
biết được thời gian đó tiêu ở đâu thay vì chỉ đoán.

**Lưu ý về `/clusters*`**: đọc cụm qua `clustering.src.storage.OpenSearchStore` (Nam), mà
lớp này **bắt buộc `STORAGE_BACKEND=opensearch`**. Khi chạy `STORAGE_BACKEND=memory`,
`/health` và `/search` vẫn hoạt động bình thường, riêng `/clusters*` trả `503` kèm lý do rõ
ràng — không làm sập cả service.

Test: `pip install -r query-api/requirements-dev.txt && cd query-api && pytest`

## AI Assistant

Hỗ trợ điều tra & đề xuất cách sửa cho một cụm lỗi — mô phỏng theo
[Elastic Observability AI Assistant](https://www.elastic.co/docs/solutions/observability/ai/observability-ai-assistant),
thu gọn cho tài nguyên hiện tại: thay vì knowledge base dạng embedding (ELSER/E5, cần node ML
riêng), AI tự gọi lại **dữ liệu thật đã có sẵn** qua function calling (xem `src/assistant/tools.py`:
`get_cluster_history`, `search_related_logs`, `list_active_clusters`) trước khi trả lời — không
bịa đặt dựa trên 1 đoạn text tĩnh.

- **Model**: OpenAI `gpt-4o-mini` (đổi qua `OPENAI_MODEL`). **Bắt buộc** tự điền `OPENAI_API_KEY`
  thật vào `.env` (không commit) — thiếu key thì `/assistant/*` trả `503`, các endpoint khác
  **không** bị ảnh hưởng.
- **Theo dõi chi phí/độ trễ/token**: qua [Langfuse](https://jp.cloud.langfuse.com) — tự động,
  không cần đổi code gọi OpenAI (dùng `langfuse.openai.OpenAI`, drop-in thay `openai.OpenAI`).
  Để trống `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` thì assistant vẫn chạy bình thường, chỉ
  không gửi trace đi.
- **Lưu hội thoại**: 1 conversation/cụm, index `assistant-conversations` (xem
  [`assistant-conversation-schema.json`](../docs/architect/contracts/assistant-conversation-schema.json)).
  Mở lại Incident View vẫn thấy lại câu hỏi/trả lời cũ.
- **Bảo vệ chi phí**: `ASSISTANT_MAX_TOOL_ROUNDS` (mặc định 5) giới hạn số vòng AI tự gọi tool
  trong 1 lượt chat, tránh vòng lặp không điểm dừng.
- **Chưa gắn auth** (PR Auth của Mạnh chưa merge) — khi merge, nhớ thêm `Depends(require_admin)`
  vào 2 route `/assistant/*` giống các route khác, vì đây là dữ liệu log/stack trace nội bộ và
  gọi API có phí.

```bash
curl -X POST "http://localhost:8002/assistant/clusters/<cluster_id>/conversation/messages" \
  -H "Content-Type: application/json" -d '{"message": "Lỗi này do đâu, cách sửa thế nào?"}'
```

## Evidence sở hữu

- **Runbook**: [`../docs/task/runbook.md`](../docs/task/runbook.md)
- **Load test end-to-end**: `../load-tests/` — mô phỏng tải thật qua toàn bộ pipeline (ingest → cluster → alert → query)
