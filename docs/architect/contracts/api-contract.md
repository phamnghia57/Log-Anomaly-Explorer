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

### `POST /ingest/batch` (bổ sung tương thích)
Nhận **JSON array** 1..`INGEST_MAX_BATCH_SIZE` structured logs (`log-schema.json` không đổi).
- **202**: `{ "accepted": true, "accepted_count": 2, "log_ids": ["...", "..."] }`
- **400**: bất kỳ item không hợp lệ → quarantine các item sai, không ghi item nào của batch, `{ "accepted": false, "reason": "schema_validation_failed", "errors": [{ "index": 0, "details": ["..."] }] }`.
- **422**: body không phải `list[object]`; **429**: vượt RPS (header `Retry-After: 1`); **503**: storage không khả dụng (Bulk có thể đã ghi một phần). Giới hạn rate tính cho cả `/ingest` và `/ingest/batch` theo process.


## Query & Incident API (Nghĩa)

### `GET /search`
Tìm log thô theo field — **không phải** semantic/vector search.

| Query param | Kiểu | Bắt buộc |
|---|---|---|
| `from`, `to` | ISO 8601 datetime | Không (mặc định 24h gần nhất) |
| `service` | string | Không |
| `trace_id` | string | Không |
| `level` | `DEBUG` / `INFO` / `WARN` / `ERROR` / `FATAL` | Không |
| `q` | string (full-text trên `message`) | Không |

Response: danh sách log theo `log-schema.json`, kèm `total`.

### `GET /search/aggregations` (JWT admin)
Nhận cùng các bộ lọc `service`, `level`, `trace_id`, `q`, `from`, `to`, thêm `interval=hour|day` (mặc định hour); khi không có `from`/`to`, mặc định 24h.

```json
{
  "histogram": [{"time": "2026-11-02T10:00:00.000Z", "count": 12}],
  "levels": [{"key": "ERROR", "count": 8}],
  "services": [{"key": "demo-web", "count": 12}]
}
```


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

Chi tiết cũng trả `incident` với `episode_id`, `status` (`open`, `acknowledged`,
`resolved`), `window_from`, `window_to` và thông tin người thao tác sau khi lưu.
`incident: null` cho biết kho xử lý sự cố không khả dụng.

### `PATCH /clusters/{cluster_id}`

Yêu cầu Bearer JWT admin. Gửi `episode_id` và `action` là `acknowledge` hoặc
`resolve`. Resolve cần `disposition` (`confirmed_incident` hoặc `false_positive`),
`note` và khoảng `[window_from, window_to)` có múi giờ. Trả 200 với bản ghi
incident, 404 khi thiếu cluster, 409 khi đợt hoặc trạng thái đã thay đổi, 422
khi body sai và 503 khi kho không khả dụng. Có thể đóng trực tiếp từ trạng thái
open. Detector vẫn cung cấp `status` của cluster và biểu đồ score.

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

### `GET /clustering/health`

Health public cho tiến độ clustering. Trả 200 với `status="ok"` và
`last_processed_at` (UTC) khi worker hoàn tất chu kỳ gần đây. Trả 503 với
`status="degraded"` và `reason` là `missing`, `stale` hoặc `storage_unavailable`
khi chưa có heartbeat, quá ba chu kỳ `WINDOW_SECONDS` hoặc không đọc được kho.
Worker cập nhật cả khi không có cụm. Replay bằng `--window-to` không cập nhật heartbeat.

## Auth — persistent sessions (#73)

Design/rollout proposed for review through Draft PR #74. Existing query/ingestion/cluster response
contracts remain unchanged. Operators initialize the users mapping and `auth-sessions`
index explicitly; there is no public registration or password-reset endpoint.

- `POST /auth/login`: JSON `{username, password}`. Success 200 `{token, expires_at}`
  with a rotating refresh cookie; invalid credentials/account 401, invalid JSON/fields
  422 with sanitized `detail="Invalid login request"`, unavailable auth/storage 503.
  A depleted per-account login budget returns 429 with `Retry-After` in seconds.
- `POST /auth/refresh`: refresh cookie only, no token in query/body. Success 200 has the
  same access response shape and replaces the cookie. Invalid/expired/reused refresh 401;
  storage/config failure 503. Replay of a previously issued refresh token revokes its session.
- `POST /auth/logout`: revokes the cookie's session and clears the cookie, idempotent 204.
  An expired access token does not prevent logout. Storage failure is 503 and is not success.
- Every auth POST requires `X-CSRF-Protection: 1`. If `Origin` is supplied it must match
  `AUTH_ALLOWED_ORIGINS`; `null` is rejected. Origin/CSRF failure is 403. Every auth response
  (including errors) has `Cache-Control: no-store` and `Pragma: no-cache`.
- Cookie `lae_refresh`: HttpOnly, Secure by default, SameSite=Lax, host-only,
  `Path=/api/auth`, absolute lifetime 7 days. The browser calls `/api/auth/*` on its own
  origin through Vercel/Vite; upstream FastAPI paths remain `/auth/*`.
- Access JWT: HS256, `sub`, `role=admin`, `sid`, `ver`, `token_use=access`, `iat`, `exp`.
  Default lifetime 900 seconds, capped at session expiry. Refresh JWT has `token_use=refresh`
  and random `jti`; rotation does not extend the absolute session expiry. Types cannot substitute
  for each other. JWT_SECRET is mandatory (at least 32 UTF-8 bytes); algorithms are allowlisted.
- Protected query/aggregation/assistant routes require `Authorization: Bearer <access JWT>`.
  Every request reads the current user and session by ID in realtime. Missing, disabled,
  non-admin, revoked, expired or version-mismatched identity/session is 401 with the existing
  generic detail and `WWW-Authenticate: Bearer`. Expired access additionally has
  `X-Auth-Reason: access_expired`. Storage/config unavailable is 503; authentication is never bypassed.
- Logout revokes the browser session. CLI disable/enable/role/password/revoke-all changes
  the account version atomically and invalidates every session. Already authorized in-flight
  requests can finish; subsequent authorization attempts see the change.
- `/health`, OPTIONS and existing API docs remain public. `/metrics` remains internal.
- The browser stores access tokens in RAM, restores through the cookie and removes legacy
  localStorage tokens. See [session runbook](../../task/jwt-sessions.md) for configuration,
  migration, CLI, tests and deployment gates.

## AI Assistant (Nghĩa) — dựa theo Elastic Observability AI Assistant, thu gọn cho tài nguyên hiện tại

Hỗ trợ điều tra & đề xuất cách sửa cho một cụm lỗi — dùng **Azure OpenAI** (model `gpt-5-mini`)
với function calling để AI tự tra cứu dữ liệu thật thay vì chỉ trả lời dựa trên 1 đoạn text tĩnh.
Hai endpoint hội thoại bên dưới yêu cầu JWT admin giống các Query API routes; thiếu/sai/hết hạn
token trả 401 trước khi đọc dữ liệu hoặc gọi Azure OpenAI. Riêng `GET /assistant/health`
**không** yêu cầu token (xem bên dưới).

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

### `GET /assistant/health`
Tình trạng AI Assistant cho trang "Trạng thái hệ thống" — **không yêu cầu token** (giống
`/health`, `/ingestion/health`, `/demo/health`: trang status đọc bằng `fetch` thường, không kèm
`Authorization`). Chỉ đọc cấu hình + **kết quả lần gọi Azure OpenAI gần nhất** đã lưu trong bộ
nhớ process — **không** gọi Azure OpenAI thật, vì trang status poll 15s/lần (gọi thật sẽ tốn phí).

**Luôn trả HTTP 200** (khác `/health` của service, có thể trả 503): đây không phải healthcheck
của container mà là một dòng thông tin trên UI — trả 503 sẽ khiến UI chỉ hiện "HTTP 503" thay vì
lý do thật trong `status`.

```json
{ "status": "ok", "service": "ai-assistant", "model": "gpt-5-mini", "last_call_at": "..." }
```

Các giá trị `status` khác: `"kho hội thoại chưa sẵn sàng"` (`STORAGE_BACKEND=memory`/OpenSearch
chưa lên), `"chưa cấu hình"` (thiếu `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`), và
`"lỗi gọi gần nhất: <TênLỗi>"` (vd. hết quota, bị chặn vùng) — chỉ `"ok"` được UI coi là bình thường.

Dữ liệu lưu theo [`assistant-conversation-schema.json`](./assistant-conversation-schema.json),
index `assistant-conversations` (env `ASSISTANT_CONVERSATIONS_INDEX`).

**Tool AI có thể tự gọi** (chỉ đọc, xem `query-api/src/assistant/tools.py`): `get_cluster_history`
(xu hướng score của cụm đang hỏi), `search_related_logs` (log khác liên quan, mặc định 24h gần
nhất), `list_active_clusters` (cụm khác đang bất thường cùng lúc — kiểm tra lan sang service
khác). Giới hạn `ASSISTANT_MAX_TOOL_ROUNDS` vòng gọi tool/lượt chat (mặc định 2) để bảo vệ chi
phí Azure OpenAI và độ trễ.

**Giới hạn ngữ cảnh gửi đi**: mỗi lượt hỏi tiếp gửi lại lịch sử hội thoại làm ngữ cảnh, nên chi
phí token tăng dần theo độ dài hội thoại. `ASSISTANT_MAX_HISTORY_MESSAGES` (mặc định 20) chặn số
message cũ được gửi lại — hội thoại vẫn **lưu đầy đủ**, chỉ phần gửi lên model bị cắt (và luôn
cắt về đầu một lượt `user` để không để lại message `tool` mồ côi làm API trả 400).

**Retention**: `ASSISTANT_RETENTION_DAYS` (mặc định 30) xoá hội thoại không được hỏi tiếp quá số
ngày này, theo `updated_at`. Job nền chạy mỗi `ASSISTANT_RETENTION_INTERVAL_SECONDS` giây (mặc
định 86400); đặt `0` để tắt và chạy bằng cron ngoài:
`python -m query-api.src.assistant.retention`.

**Theo dõi chi phí/độ trễ**: qua Langfuse (`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, miền
`https://jp.cloud.langfuse.com`) — tự động, không cần đổi code gọi Azure OpenAI (dùng wrapper
`langfuse.openai.OpenAI` trỏ `base_url` vào `<endpoint>/openai/v1/`). Để trống 2 key thì assistant
vẫn chạy bình thường, chỉ không gửi trace.
