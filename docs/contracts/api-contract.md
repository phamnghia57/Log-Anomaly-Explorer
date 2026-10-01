# API Contract

Hợp đồng giữa tầng dữ liệu (ingestion, clustering) và query-api (Nghĩa). Đóng băng ở Ngày 0 — mọi thay đổi phải thông báo cho cả nhóm trước khi sửa.

## Ingestion Service (Minh)

### `POST /ingest`
Nhận một structured log, validate theo [`log-schema.json`](./log-schema.json).

- **Request body**: theo `log-schema.json`
- **Response 202**: `{ "accepted": true, "log_id": "<id>" }`
- **Response 400**: log sai schema → đưa vào quarantine, không chèn vào index chính
  ```json
  { "accepted": false, "reason": "schema_validation_failed", "details": "..." }
  ```

## Query & Incident API (Nghĩa)

### `GET /search`
Tìm log thô theo field — **không phải** semantic/vector search.

| Query param | Kiểu | Bắt buộc |
|---|---|---|
| `from`, `to` | ISO 8601 datetime | Không (mặc định 24h gần nhất) |
| `service` | string | Không |
| `trace_id` | string | Không |
| `q` | string (full-text trên `message`) | Không |

Response: danh sách log theo `log-schema.json`, kèm `total`.

### `GET /clusters`
Danh sách cụm bất thường, đọc từ dữ liệu do Nam ghi theo [`cluster-record.schema.json`](./cluster-record.schema.json).

| Query param | Kiểu | Ghi chú |
|---|---|---|
| `status` | `anomalous` \| `alerted` \| `normal` | Lọc theo trạng thái |
| `since` | ISO 8601 datetime | Mặc định theo retention hiện hành |

### `GET /clusters/{cluster_id}`
Chi tiết một cụm — dùng cho Incident View.

Response:
```json
{
  "cluster_id": "...",
  "score": 0.0,
  "status": "anomalous",
  "logs": [ /* StructuredLog[] theo log-schema.json, tra ve tu log_ids */ ],
  "trace_ids": ["..."]
}
```

## Alert (Nam → kênh thông báo ngoài)

Khi `score > ngưỡng`, Clustering service tự gọi webhook/email cấu hình sẵn — **không** đi qua query-api. Payload tối thiểu:

```json
{ "cluster_id": "...", "score": 0.0, "service": "...", "first_seen": "..." }
```
