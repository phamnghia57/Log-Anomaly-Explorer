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

Các route `/search` và `/clusters*` bên dưới yêu cầu JWT admin trong header
`Authorization: Bearer <token>`. `/health` và `/auth/login` không yêu cầu JWT.

| Endpoint | Tham số | Ghi chú |
|---|---|---|
| `GET /health` | — | `503 degraded` khi mất kết nối kho dữ liệu |
| `GET /search` | `service`, `trace_id`, `q`, `from`, `to`, `limit`, `offset` | Mặc định 24h gần nhất; `total` không bị cắt bởi `limit` |
| `GET /clusters` | `status`, `since`, `limit`, `offset` | Mặc định `since` theo `RETENTION_DAYS` |
| `GET /clusters/{id}` | `logs_limit`, `logs_offset` | Incident View: cụm + `logs` tra từ `log_ids`, **có phân trang** (`logs_total` = tổng số log của cụm) |
| `GET /clusters/{id}/history` | `since`, `limit` | Xu hướng anomaly score theo thời gian (index `cluster-history`) |
| `GET /metrics` | — | Metrics dạng Prometheus, **không** route ra Internet qua gateway |
| `POST /auth/login` | JSON `username`, `password` | Đăng nhập admin, trả JWT và `expires_at` |
| `GET /assistant/clusters/{id}/conversation` | — | Hội thoại điều tra với AI Assistant (xem mục riêng bên dưới) |
| `POST /assistant/clusters/{id}/conversation/messages` | body `{"message": "..."}` | Gửi câu hỏi cho AI Assistant |

```bash
# TOKEN la JWT nhan tu POST /auth/login (xem vi du PowerShell ben duoi).
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8002/search?service=demo-web&q=timeout&limit=20"
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8002/clusters?status=alerted"
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8002/clusters/<cluster_id>?logs_limit=50"
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8002/clusters/<cluster_id>/history"
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
`/health` vẫn public; `/search` hoạt động khi có JWT admin hợp lệ. Với cùng JWT đó,
`/clusters*` trả `503` kèm lý do rõ ràng — không làm sập cả service. Guard JWT vẫn áp dụng
trong memory mode; mode này không hỗ trợ login/seed admin.

Test: `pip install -r query-api/requirements-dev.txt && cd query-api && pytest`

## Chuẩn bị cấu hình JWT admin

`src/config.py` đọc cấu hình auth từ environment khi import, theo cách cấu hình hiện có
của ingestion. User repository dùng client từ `ingestion.src.storage.build_store()` hoặc
`OpenSearchLogStore` truyền vào, giữ nguyên URL, credentials, TLS, timeout và shard settings
hiện có. User dùng index riêng trên cùng OpenSearch theo `users-schema.json`.

- `JWT_SECRET`: không có mặc định. Login/JWT utilities từ chối secret thiếu, rỗng, chỉ có
  khoảng trắng hoặc ngắn hơn 32 bytes UTF-8. Cung cấp secret ngẫu nhiên từ môi trường triển khai.
- `JWT_EXPIRY_SECONDS`: số nguyên dương, mặc định `3600`; giá trị không hợp lệ báo lỗi.
- `ADMIN_SEED_USERNAME`, `ADMIN_SEED_PASSWORD`: bắt buộc khi chạy lệnh seed admin;
  không có tài khoản/mật khẩu mặc định và không log các giá trị này.
- `USERS_INDEX`: mặc định `users`, không chấp nhận tên rỗng.

Docker Compose truyền năm biến trên vào query-api; `.env.example` chỉ chứa giá trị trống
cho secret và seed credentials. Đặt giá trị thật trong môi trường triển khai hoặc `.env`
đã được Git ignore. Khi chạy uvicorn trực tiếp, export biến vào môi trường tiến trình;
module config không tự đọc `.env`.

## Seed admin bằng lệnh riêng

Nạp `ADMIN_SEED_USERNAME` và `ADMIN_SEED_PASSWORD` vào environment từ nguồn bí mật của bạn.
Không đưa password vào command arguments, file được Git theo dõi hoặc log. Khi chạy trực
tiếp, cần `STORAGE_BACKEND=opensearch` và OpenSearch hiện có phải truy cập được qua
`OPENSEARCH_URL` cùng các biến `OPENSEARCH_*` của ingestion. Không hỗ trợ lưu user vào memory.

Từ thư mục gốc repo, sau khi cài dependencies:

```bash
python -m pip install -r query-api/requirements.txt
python -m query-api.src.seed_admin
```

Với Docker Compose, điền credentials vào `.env` đã được Git ignore hoặc environment,
đảm bảo OpenSearch đang chạy, rồi build lại image và chạy one-off command:

```bash
docker compose build query-api
docker compose run --rm --no-deps query-api python -m query-api.src.seed_admin
```

Lệnh tạo `USERS_INDEX` nếu thiếu, dùng strict mapping với đúng các field trong schema.
Admin mới có `username`, `password_hash`, `role="admin"`, `created_at` UTC; seed không đặt
`last_login_at`. Document `_id` chính là username. Password được hash
bằng [argon2-cffi PasswordHasher](https://argon2-cffi.readthedocs.io/en/stable/howto.html)
(Argon2id, salt ngẫu nhiên); chỉ hash được lưu trong `_source`, không index hash để tìm kiếm.

Chỉ lệnh trên mới seed; không tự chạy khi API khởi động. Nếu account đã tồn tại, lệnh
báo `Existing account preserved; no changes made.` và giữ nguyên hash, role, timestamps,
kể cả khi environment chứa password mới. Ghi bằng OpenSearch `_create` để hai tiến trình
seed đồng thời cũng không ghi đè nhau. Đây không phải lệnh reset/rotate password.

Exit code `0`: tạo mới hoặc giữ account hiện có. Exit code `1`: thiếu credentials,
backend không hợp lệ, lỗi hashing hoặc OpenSearch; thông báo không in password/chi tiết
response. Thiếu credentials được kiểm tra trước mọi thao tác storage. Seed không phát JWT
nên không yêu cầu `JWT_SECRET`; login/JWT vẫn bắt buộc có secret riêng.

Chạy tests từ `query-api/`: `python -m pytest -q`. Tests dùng OpenSearch mock và Argon2
thật, kiểm tra schema, create-only, seed lặp, bảo toàn account cũ, race conditions, cấu hình
thiếu, lỗi storage, cleanup và thông báo CLI không chứa password. Không cần live cluster.

## Đăng nhập admin và JWT

`POST /auth/login` nhận JSON `{"username": "...", "password": "..."}`. API đọc user theo
username từ `USERS_INDEX` bằng repository dùng chung client OpenSearch của log store,
verify Argon2 hash và chỉ cho account có `role="admin"` đăng nhập. Không seed/tạo index
hay cập nhật account trong request login. Backend `memory` không hỗ trợ đăng nhập.

Thành công trả `{"token": "<JWT>", "expires_at": "<ISO-8601 UTC>"}`, với header
`Cache-Control: no-store`. JWT ký bằng HS256 và `JWT_SECRET`, chứa `sub` (username),
`role="admin"`, `exp`; thời hạn lấy từ `JWT_EXPIRY_SECONDS` (mặc định 3600 giây).
`expires_at` và `exp` biểu diễn đúng cùng thời điểm hết hạn, không có leeway.

Sai username/password trả `401 {"detail": "Invalid username or password"}` giống nhau.
Username không tồn tại vẫn chạy verify với dummy hash để không bỏ qua chi phí Argon2.
Thiếu/không dùng được secret trả `503 Authentication unavailable`; OpenSearch/index users
không sẵn sàng trả `503 User storage unavailable`, không đưa chi tiết lỗi storage vào response.

Ví dụ PowerShell dùng credentials đã nạp vào environment, gọi trực tiếp cổng query-api:

```powershell
$body = @{
    username = $env:ADMIN_SEED_USERNAME
    password = $env:ADMIN_SEED_PASSWORD
} | ConvertTo-Json
$login = Invoke-RestMethod -Method Post http://localhost:8002/auth/login `
    -ContentType "application/json" -Body $body
$login.expires_at
$headers = @{ Authorization = "Bearer $($login.token)" }
Invoke-RestMethod "http://localhost:8002/search?limit=5" -Headers $headers
```

Giữ `$login.token` trong bộ nhớ và đính kèm ở header; không in token/password/secret
vào log. Đổi cổng URL nếu `QUERY_API_PORT` khác mặc định. Gateway đã proxy chính xác
`/auth/login` (POST và OPTIONS) tới query-api; không strip Authorization của query requests.
Frontend có `/login`, guard và logout. Request login sai shape/JSON trả
`422 {"detail":"Invalid login request"}`, không echo lại input có thể chứa mật khẩu.

`src/tokens.py::decode_access_token()` luôn verify signature với allowlist cố định `["HS256"]`,
yêu cầu đủ `sub`, `role`, `exp`, kiểm tra admin role và expiration. Không lấy algorithm từ
token header; token unsigned, algorithm khác, sai signature, thiếu claim hoặc hết hạn bị từ chối.
Xem [PyJWT API](https://pyjwt.readthedocs.io/en/stable/api.html).

Tests trong `tests/test_admin_login.py` mock OpenSearch, dùng Argon2/PyJWT thật và clock
cố định để kiểm tra login, claims/lifetime, expiration boundary, signature/algorithm rejection,
cấu hình thiếu/sai, lỗi storage và bảo mật log. Không cần live cluster hoặc sleep để đợi JWT hết hạn.

## Bảo vệ Query API

`src/auth.py::require_admin()` là dependency dùng lại được, được gắn riêng vào bốn route:
`GET /search`, `GET /clusters`, `GET /clusters/{cluster_id}` và
`GET /clusters/{cluster_id}/history`. Dependency đọc Bearer token từ `Authorization`, gọi
JWT utility để kiểm tra signature, HS256 allowlist, expiration, đủ claims và role admin.
Không chấp nhận token qua query string. Response thành công và query parameters giữ nguyên.

Thiếu header/token, sai scheme, JWT malformed, sai signature, hết hạn, thiếu/sai claims
hoặc role khác admin đều trả `401 {"detail": "Invalid or missing authentication token"}`,
kèm `WWW-Authenticate: Bearer`. Lỗi bị chặn trước khi đọc log/cluster storage. Nếu server
không cấu hình được JWT, request có token trả `503 Authentication unavailable`; không có
fallback bỏ qua auth.

`GET /health` và `POST /auth/login` vẫn public, kể cả khi request kèm Bearer token không hợp lệ.
CORS middleware xử lý OPTIONS preflight trước dependency; frontend được phép gửi header
`Authorization` cho GET và JSON login POST. Response 401 cũng có CORS headers để frontend
đọc status và xử lý đăng nhập lại.

`tests/test_query_auth.py` kiểm tra các trường hợp từ chối trên từng route, không gọi storage
khi bị chặn, response với token admin, query-string token, CORS/preflight và cấu hình JWT lỗi.
Các regression tests trong `tests/test_query_api.py` dùng JWT ký thật để tiếp tục kiểm tra
filters, pagination, response và lỗi storage; không override dependency để bỏ qua auth.

Không có signup/registration/password reset. Frontend xóa session/cache khi logout, hết hạn
hoặc gặp 401; logout không thu hồi JWT ở server. JWT đã phát còn dùng được tới `exp`;
đổi role/xóa user không vô hiệu token đã phát ngay lập tức. Chưa có refresh/revocation,
rate limiting/lockout cho login, issuer/audience claims hoặc MFA. CORS hiện cho mọi origin,
không dùng cookie credentials; CORS không thay thế xác thực/ủy quyền.

Hướng dẫn secret an toàn, Compose/gateway, seed, kiểm tra protected APIs và các giới hạn:
[`docs/task/auth-deployment.md`](../docs/task/auth-deployment.md). Không đổi frozen contracts
hoặc schema phản hồi thành công của API hiện có.

## Kiểm thử tích hợp auth

`python -m pytest -q` chạy tất cả tests Query API. `test_auth_integration.py` nối cùng một
mock client OpenSearch qua repository, seed, Argon2, login/JWT và cả bốn protected routes;
đối chiếu users/log/cluster với frozen JSON schemas và kiểm tra response hiện có. Các test
khác kiểm tra lỗi storage, CORS/OPTIONS, thiếu/sai/hết hạn token và password không bị echo
trong 422/log. Không cần live OpenSearch hoặc Jaeger cho suite này.

Browser integration có API HTTP thật trên loopback, chỉ mock OpenSearch client. Cài Python
dependencies, đưa Python của venv vào PATH, rồi chạy từ `web/`:

```bash
npm run test:auth-integration -- --reporter=line
```

Lệnh dùng `python -m query-api.tests.auth_test_server` (test-only, không có trong image vì
`.dockerignore` loại `tests/`). Harness sinh credentials/secret tạm trong bộ nhớ, seed CLI
hai lần, bind `127.0.0.1:8023`; Vite ở `127.0.0.1:5174`. Playwright tự dừng cả hai sau test.
Không dùng test harness cho deploy, không xác minh persistence/mapping/TLS với cluster thật.

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
- Hai route `/assistant/*` được gắn `Depends(require_admin)` khi include router trong `main.py`,
  giống các query routes, vì đây là dữ liệu log/stack trace nội bộ và gọi API có phí.

```bash
curl -X POST "http://localhost:8002/assistant/clusters/<cluster_id>/conversation/messages" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message": "Lỗi này do đâu, cách sửa thế nào?"}'
```

## Evidence sở hữu

- **Runbook**: [`../docs/task/runbook.md`](../docs/task/runbook.md)
- **Load test end-to-end**: `../load-tests/` — mô phỏng tải thật qua toàn bộ pipeline (ingest → cluster → alert → query)
