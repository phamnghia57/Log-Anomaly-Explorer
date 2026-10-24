# API Contract

Hợp đồng giữa tầng dữ liệu (ingestion, clustering) và query-api (Nghĩa). Đóng băng ở Ngày 0 — mọi thay đổi phải thông báo cho cả nhóm trước khi sửa.

> **Bổ sung (đợt nâng cấp 2026-10-24)**: thêm `GET /clusters/{cluster_id}/history` (xu hướng
> anomaly score) và mục "Auth (dự kiến)" ở cuối file — không đổi/không đụng bất kỳ phần nào đã
> đóng băng phía trên.

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

### `GET /clusters/{cluster_id}/history`
Lịch sử anomaly score theo thời gian của **một cụm** — dùng vẽ biểu đồ xu hướng trong Incident
View (khác `GET /clusters/{cluster_id}`: endpoint đó chỉ trả 1 điểm số hiện tại). Đọc từ index
`cluster-history` (`HISTORY_INDEX` trong `.env`, mặc định `cluster-history`), ghi theo
[`cluster-history-schema.json`](./cluster-history-schema.json) — **Nam ghi mỗi chu kỳ tính
toán** (1 điểm/chu kỳ/cụm), **không đụng** `cluster-record.schema.json`.

| Query param | Kiểu | Ghi chú |
|---|---|---|
| `since` | ISO 8601 datetime | Mặc định theo retention hiện hành (giống `GET /clusters`) |
| `limit` | int | Mặc định 100, tối đa 1000 |

Response (sắp theo `recorded_at` tăng dần, để vẽ chart trái→phải theo thời gian):
```json
{
  "cluster_id": "...",
  "points": [
    { "recorded_at": "...", "score": 0.0, "status": "anomalous" }
  ]
}
```

404 nếu `cluster_id` không tồn tại trong `clusters` (dùng `GET /clusters/{cluster_id}` để biết
cụm có tồn tại không). `points` rỗng là hợp lệ (cụm tồn tại nhưng clustering chưa ghi history —
ví dụ trước khi Nam triển khai phần ghi).

## Alert (Nam → kênh thông báo ngoài)

Khi `score > ngưỡng`, Clustering service tự gọi webhook/email cấu hình sẵn — **không** đi qua query-api. Payload tối thiểu:

```json
{ "cluster_id": "...", "score": 0.0, "service": "...", "first_seen": "..." }
```

## Auth (dự kiến — CHỈ thiết kế, chưa implement)

> Mục này chỉ là **contract/thiết kế** để người nhận việc Auth code theo, tránh mỗi người tự
> đoán 1 kiểu. Chưa có code nào tương ứng — xem `docs/architect/contracts/users-schema.json`.

- **Phạm vi**: chỉ đăng nhập (login), **không có public signup**. Tài khoản admin được seed sẵn
  (qua biến môi trường lúc khởi động, hoặc tạo tay 1 lần qua script) — không expose
  `POST /auth/register` ra public.
- **Lưu trữ**: 1 index mới `users` trong OpenSearch sẵn có (không thêm database/container mới).
  Document shape: xem [`users-schema.json`](./users-schema.json).
- **`POST /auth/login`**
  - Request: `{ "username": "...", "password": "..." }`
  - Response 200: `{ "token": "<JWT>", "expires_at": "..." }`
  - Response 401: sai username/password — không phân biệt rõ sai cái nào (tránh dò username).
- **JWT claims tối thiểu**: `sub` (username), `role` (hiện tại chỉ có `"admin"`), `exp`.
  Ký bằng secret đọc từ env `JWT_SECRET` (bắt buộc set khi deploy, không có default).
- **Áp dụng JWT**: các route cần bảo vệ (`GET /search`, `GET /clusters`, `GET /clusters/{id}`,
  `GET /clusters/{id}/history`) yêu cầu header `Authorization: Bearer <token>`. `GET /health`
  **không** yêu cầu auth (dùng cho health check hạ tầng). Thiếu/sai token → 401.
- **Phía `web/`**: 1 trang `/login`, lưu token (ví dụ `localStorage`), đính kèm header
  `Authorization` ở tầng client chung (`web/src/lib/api.ts`), redirect về `/login` khi API trả
  401. Route còn lại trong `web/` yêu cầu đã đăng nhập (route guard).
- **Env cần thêm khi implement**: `JWT_SECRET`, `JWT_EXPIRY_SECONDS` (gợi ý mặc định `3600`),
  `ADMIN_SEED_USERNAME`, `ADMIN_SEED_PASSWORD` (chỉ dùng lúc seed lần đầu, không log lại).
