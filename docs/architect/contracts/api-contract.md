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

## Auth (đã triển khai)

> Đã triển khai trong [Query API](../../../query-api/src/auth.py),
> [JWT utilities](../../../query-api/src/tokens.py) và [web](../../../web/src/App.tsx).
> Mô tả dưới đây đồng bộ với code hiện có; giữ nguyên cấu trúc request/response đã thống nhất.

- **Phạm vi**: chỉ đăng nhập (login), **không có public signup**. Tài khoản admin được seed sẵn
  bằng lệnh riêng `python -m query-api.src.seed_admin`, đọc credentials từ environment;
  không tự seed khi API khởi động. Không có `POST /auth/register`, signup hoặc password-reset API.
- **Lưu trữ**: index `users` (cấu hình qua `USERS_INDEX`) trong OpenSearch sẵn có, không thêm
  database/container. Document shape theo [`users-schema.json`](./users-schema.json), dùng
  username làm document ID và lưu `password_hash` Argon2id, không lưu plaintext password.
- **`POST /auth/login`**
  - Request JSON: `{ "username": "...", "password": "..." }`
  - Response 200: `{ "token": "<JWT>", "expires_at": "..." }`, với `expires_at` là ISO-8601 UTC
    cùng thời điểm với claim `exp`; response có `Cache-Control: no-store`.
  - Response 401: `{ "detail": "Invalid username or password" }` cho sai username/password
    hoặc account không hợp lệ — không phân biệt rõ sai cái nào (tránh dò username).
  - JSON/fields không hợp lệ trả 422 với `detail="Invalid login request"`, không echo input.
    Cấu hình JWT hoặc user storage không sẵn sàng trả 503 với thông báo chung.
- **JWT claims**: `sub` là username, `role="admin"`, `exp` là Unix timestamp (giây).
  Ký và verify bằng HS256 với allowlist cố định; yêu cầu đủ ba claims, kiểm tra signature,
  role admin và expiration. Không chấp nhận unsigned token/algorithm khác hoặc token hết hạn.
  Secret đọc từ env `JWT_SECRET` (bắt buộc, ít nhất 32 bytes UTF-8, không có fallback).
  Lifetime lấy từ `JWT_EXPIRY_SECONDS`, mặc định `3600` giây, không có expiry leeway.
- **Áp dụng JWT**: `GET /search`, `GET /clusters`, `GET /clusters/{cluster_id}` và
  `GET /clusters/{cluster_id}/history` có dependency `require_admin`, yêu cầu header
  `Authorization: Bearer <token>`. Không nhận token qua query string. Thiếu, malformed, sai
  signature/claims/role hoặc hết hạn → 401 với `WWW-Authenticate: Bearer`. Query parameters
  và cấu trúc response thành công giữ nguyên.
- **Public**: `GET /health` và `POST /auth/login` không yêu cầu JWT; CORS OPTIONS preflight
  cho GET/POST và Authorization/Content-Type cũng không yêu cầu JWT. `/metrics` không gắn
  guard nhưng chỉ dành cho mạng nội bộ, không được gateway proxy ra Internet. Các route
  tài liệu tự sinh `/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json` vẫn không gắn JWT.
- **Phía `web/`**: trang `/login` lưu `{token, expires_at}` trong module auth/localStorage,
  không lưu password; đính kèm header
  `Authorization` ở tầng client chung (`web/src/lib/api.ts`), redirect về `/login` khi API trả
  401 hoặc session hết hạn. Dashboard, Search và Incident View yêu cầu đăng nhập (route guard).
  Logout xóa session/cache ở client; không thu hồi JWT đã phát trước `exp`. Backend vẫn là
  nơi quyết định quyền truy cập, không dựa vào frontend guard.
- **Env hiện có**: `JWT_SECRET`, `JWT_EXPIRY_SECONDS` (mặc định `3600`), `USERS_INDEX`
  (mặc định `users`), `ADMIN_SEED_USERNAME`, `ADMIN_SEED_PASSWORD` (chỉ dùng khi seed, không log).
  Hướng dẫn chạy/seed: [triển khai auth](../../task/auth-deployment.md).
- **AI Assistant**: hai route GET/POST ở mục dưới cũng dùng `Depends(require_admin)` và
  `Authorization: Bearer <token>` vì đọc log/stack trace nội bộ và gọi API có phí.

## AI Assistant (Nghĩa) — dựa theo Elastic Observability AI Assistant, thu gọn cho tài nguyên hiện tại

Hỗ trợ điều tra & đề xuất cách sửa cho một cụm lỗi — dùng **Azure OpenAI** (model `gpt-5-mini`)
với function calling để AI tự tra cứu dữ liệu thật thay vì chỉ trả lời dựa trên 1 đoạn text tĩnh.
Hai endpoint dưới đây yêu cầu JWT admin giống các Query API routes; thiếu/sai/hết hạn token
trả 401 trước khi đọc dữ liệu hoặc gọi Azure OpenAI.

**Vì sao Azure OpenAI, không dùng OpenAI trực tiếp**: VM chạy ở vùng Azure "East Asia" (Hong
Kong). OpenAI chặn request theo IP của vùng này (`unsupported_country_region_territory`) — Hong
Kong không nằm trong danh sách vùng được OpenAI hỗ trợ (cùng nhóm loại trừ với Trung Quốc đại
lục), dù Việt Nam vẫn được hỗ trợ. Azure OpenAI không bị chặn theo cách này: resource được tạo ở
một vùng Azure khác (không phải East Asia — vd. Southeast Asia/East US), hoàn toàn không liên
quan tới vùng của VM gọi đến nó.

### `GET /assistant/clusters/{cluster_id}/conversation`
Hội thoại điều tra hiện có của một cụm — 1 conversation/cụm (không phải nhiều thread). Trả
`messages: []` nếu chưa ai hỏi AI về cụm này lần nào (không phải lỗi).

Response:
```json
{ "cluster_id": "...", "messages": [ { "role": "user|assistant|tool", "content": "...", "created_at": "..." } ] }
```

### `POST /assistant/clusters/{cluster_id}/conversation/messages`
Gửi 1 tin nhắn, AI có thể tự gọi tool để điều tra thêm trước khi trả lời. Trả về **toàn bộ** hội
thoại đã lưu sau lượt này (không chỉ tin nhắn mới).

- Request: `{ "message": "..." }`
- Response 200: giống response của `GET` ở trên.
- Response 404: `cluster_id` không tồn tại.
- Response 503: thiếu `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`, hoặc kho hội thoại/cụm chưa
  sẵn sàng (`STORAGE_BACKEND=memory`).
- Response 502: lỗi gọi Azure OpenAI (timeout, quota, …) — không làm sập service.

Dữ liệu lưu theo [`assistant-conversation-schema.json`](./assistant-conversation-schema.json),
index `assistant-conversations` (env `ASSISTANT_CONVERSATIONS_INDEX`).

**Tool AI có thể tự gọi** (chỉ đọc, xem `query-api/src/assistant/tools.py`): `get_cluster_history`
(xu hướng score của cụm đang hỏi), `search_related_logs` (log khác liên quan, mặc định 24h gần
nhất), `list_active_clusters` (cụm khác đang bất thường cùng lúc — kiểm tra lan sang service
khác). Giới hạn `ASSISTANT_MAX_TOOL_ROUNDS` vòng gọi tool/lượt chat (mặc định 5) để bảo vệ chi
phí Azure OpenAI và độ trễ.

**Theo dõi chi phí/độ trễ**: qua Langfuse (`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, miền
`https://jp.cloud.langfuse.com`) — tự động, không cần đổi code gọi Azure OpenAI (dùng wrapper
`langfuse.openai.AzureOpenAI`). Để trống 2 key thì assistant vẫn chạy bình thường, chỉ không gửi
trace.
