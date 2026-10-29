# API Contract

Hợp đồng giữa tầng dữ liệu (ingestion, clustering) và query-api (Nghĩa). Đóng băng ở Ngày 0 — mọi thay đổi phải thông báo cho cả nhóm trước khi sửa.

> **Bổ sung (đợt nâng cấp 2026-10-24)**: thêm `GET /clusters/{cluster_id}/history` (xu hướng
> anomaly score) và mục "Auth (dự kiến)" ở cuối file — không đổi/không đụng bất kỳ phần nào đã
> đóng băng phía trên.
>
> **Bổ sung (VT-016, 2026-10-29)**: thêm `POST /ingest/bulk` — không đổi `POST /ingest` hiện có.

## Ingestion Service (Minh)

### `POST /ingest`
Nhận một structured log, validate theo [`log-schema.json`](./log-schema.json).

- **Request body**: theo `log-schema.json`
- **Response 202**: `{ "accepted": true, "log_id": "<id>" }`
- **Response 400**: log sai schema → đưa vào quarantine, không chèn vào index chính
  ```json
  { "accepted": false, "reason": "schema_validation_failed", "details": "..." }
  ```

### `POST /ingest/bulk`
Nhận nhiều structured log trong 1 request — import hàng loạt (VT-016). Mỗi phần tử validate
**độc lập** theo `log-schema.json`, y hệt `POST /ingest`.

- **Request body**: `{ "logs": [ <StructuredLog>, ... ] }` — tối thiểu 1, tối đa 500 phần tử
  (bảo vệ ngân sách p95; batch lớn hơn nên chia nhỏ ở phía gọi).
- **Response 207** (Multi-Status — kết quả hỗn hợp theo từng phần tử):
  ```json
  {
    "accepted": 3, "quarantined": 1, "failed": 0,
    "results": [
      { "index": 0, "status": "accepted", "log_id": "..." },
      { "index": 1, "status": "quarantined", "reason": "schema_validation_failed", "details": ["..."] },
      { "index": 2, "status": "failed", "reason": "storage_unavailable" }
    ]
  }
  ```
- **Response 400**: `{ "accepted": false, "reason": "empty_batch" }` hoặc
  `{ "accepted": false, "reason": "batch_too_large", "max_batch_size": 500 }` — từ chối **cả
  batch**, không ghi một phần.

**Invariant bắt buộc**: một phần tử lỗi (sai schema hoặc ghi thất bại) không được làm mất các
phần tử hợp lệ khác trong cùng batch; một phần tử **không bao giờ** được báo `"status": "accepted"`
nếu việc ghi (persist) của chính nó thất bại thật. Xem
`ingestion/tests/test_bulk_ingest.py::test_bulk_persistence_failure_never_reported_as_accepted`.

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

| Query param | Kiểu | Ghi chú |
|---|---|---|
| `logs_limit` | int | Số log trả về mỗi trang. Mặc định 100, tối đa 1000 |
| `logs_offset` | int | Mặc định 0 |

Response:
```json
{
  "cluster_id": "...",
  "score": 0.0,
  "status": "anomalous",
  "logs": [ /* StructuredLog[] theo log-schema.json, tra ve tu log_ids */ ],
  "logs_total": 0,
  "trace_ids": ["..."]
}
```

`logs` được **phân trang** — một cụm có thể gồm hàng trăm log, trả hết trong một response làm
endpoint này chậm nhất hệ thống (đo thật: median 530ms, p99 1.7s — xem `load-tests/README.md`).
`logs_total` là tổng số `log_ids` của cụm (không bị cắt bởi `logs_limit`), để UI biết còn bao
nhiêu log chưa tải. Lưu ý `len(logs)` có thể **nhỏ hơn** số lượng yêu cầu nếu log trong trang đó
đã bị retention xoá.

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
{ "cluster_id": "...", "score": 0.0, "service": "...", "first_seen": "...", "trace_id": "..." }
```

`trace_id` là **một trace đại diện** của cụm (phần tử đầu trong `trace_ids` của
[`cluster-record.schema.json`](./cluster-record.schema.json)), để kênh nhận alert ghép được link
mở thẳng trace đó trên Jaeger: `https://<domain>/jaeger/trace/<trace_id>`. Key **luôn có mặt**,
giá trị `null` khi cụm không có trace nào — bên nhận không cần xử lý trường hợp thiếu key.

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
