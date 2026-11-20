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
| `GET /search` | `service`, `level`, `trace_id`, `q`, `from`, `to`, `limit`, `offset` | Mặc định 24h gần nhất; `total` không bị cắt bởi `limit` |
| `GET /clusters` | `status`, `since`, `limit`, `offset` | Mặc định `since` theo `RETENTION_DAYS` |
| `GET /clusters/{id}` | `logs_limit`, `logs_offset` | Incident View: cụm + `logs` tra từ `log_ids`, **có phân trang** (`logs_total` = tổng số log của cụm) |
| `GET /clusters/{id}/history` | `since`, `limit` | Xu hướng anomaly score theo thời gian (index `cluster-history`) |
| `GET /metrics` | — | Metrics dạng Prometheus, **không** route ra Internet qua gateway |
| `POST /auth/login` | JSON `username`, `password` | Đăng nhập admin, trả JWT và `expires_at` |
| `GET /assistant/clusters/{id}/conversation` | — | Hội thoại điều tra với AI Assistant (xem mục riêng bên dưới) |
| `POST /assistant/clusters/{id}/conversation/messages` | body `{"message": "..."}` | Gửi câu hỏi cho AI Assistant |
| `GET /assistant/health` | — | Tình trạng AI Assistant cho trang "Trạng thái hệ thống" (không cần token) |

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

Dùng để làm gì: load test 2026-10-23 đo được `GET /clusters/{id}` là endpoint chậm nhất (median
530ms, p99 1.7s); đo lại 2026-11-13 chỉ còn median 12ms, và chỗ tốn thời gian nhất giờ là
`POST /auth/login` 160ms do Argon2id (xem [`../load-tests/README.md`](../load-tests/README.md)).
Có trace + metrics thì biết được thời gian đó tiêu ở đâu thay vì chỉ đoán.

**Lưu ý về `/clusters*`**: đọc cụm qua `clustering.src.storage.OpenSearchStore` (Nam), mà
lớp này **bắt buộc `STORAGE_BACKEND=opensearch`**. Khi chạy `STORAGE_BACKEND=memory`,
`/health` vẫn public; `/search` hoạt động khi có JWT admin hợp lệ. Với cùng JWT đó,
`/clusters*` trả `503` kèm lý do rõ ràng — không làm sập cả service. Guard JWT vẫn áp dụng
trong memory mode; mode này không hỗ trợ login/seed admin.

Test: `pip install -r query-api/requirements-dev.txt && cd query-api && pytest`

## Auth và phiên JWT (#73)

Xem [runbook phiên JWT](../docs/task/jwt-sessions.md) cho cấu hình, migration, seed,
login/refresh/logout, CLI quản trị và kiểm thử. Access token mặc định 15 phút, phiên tối đa
7 ngày, refresh rotation và kiểm tra trạng thái user/session realtime ở mỗi protected request.
Logout thu hồi phiên server; đổi quyền/mật khẩu/khóa tài khoản thu hồi mọi phiên. Lỗi storage
trả 503, token sai/đã thu hồi trả 401. Payload thành công của các API nghiệp vụ giữ nguyên.

```bash
# Sau khi cung cấp env auth/OpenSearch qua secret injection:
python -m query-api.src.manage_auth init
python -m query-api.src.seed_admin
python -m query-api.src.manage_auth revoke-all ten-tai-khoan
```

Chạy pytest riêng trong query-api. Để kiểm tra OpenSearch thật, cung cấp biến
`AUTH_TEST_OPENSEARCH_URL` tới cluster test riêng và chạy `tests/test_live_auth_sessions.py`.
Browser suite ở web gọi FastAPI qua proxy cùng origin; `AUTH_E2E_OPENSEARCH_URL` chọn storage thật.
Chế độ memory không hỗ trợ đăng nhập production. Không có signup/reset-password public.

## AI Assistant

Hỗ trợ điều tra & đề xuất cách sửa cho một cụm lỗi — mô phỏng theo
[Elastic Observability AI Assistant](https://www.elastic.co/docs/solutions/observability/ai/observability-ai-assistant),
thu gọn cho tài nguyên hiện tại: thay vì knowledge base dạng embedding (ELSER/E5, cần node ML
riêng), AI tự gọi lại **dữ liệu thật đã có sẵn** qua function calling (xem `src/assistant/tools.py`:
`get_cluster_history`, `search_related_logs`, `list_active_clusters`, `get_trace`) trước khi trả
lời — không bịa đặt dựa trên 1 đoạn text tĩnh.

- **`get_trace`** đọc trace phân tán từ Jaeger theo `trace_id` có sẵn trong log và trả về danh
  sách span (service, operation, thời gian chạy, span nào lỗi). Đây là thứ phân biệt Assistant
  này với một con bot đọc log: nó chỉ được ra **bước nào** trong request chậm hoặc hỏng, đúng
  mục tiêu "liên kết bất thường về trace/request cụ thể" của đề tài. Bật bằng `JAEGER_QUERY_URL`
  (xem `.env.example`) — **để trống thì tool này không được chào cho model**, tránh tốn một vòng
  gọi chỉ để nhận lỗi ở môi trường không có Jaeger. URL phải kèm base path nếu Jaeger chạy dưới
  tiền tố (`QUERY_BASE_PATH` trong `docker-compose.yml`), vì base path áp cho cả API lẫn UI.
  Trace cũ có thể đã bị đẩy khỏi RAM của Jaeger — khi đó tool trả `trace not found` kèm ghi chú
  để AI không kết luận nhầm là request chưa từng xảy ra.

- **Model**: `gpt-5-mini` qua **Azure OpenAI** (không dùng OpenAI trực tiếp — VM chạy ở vùng Azure
  "East Asia"/Hong Kong, bị OpenAI chặn theo IP, xem `docs/architect/contracts/api-contract.md`
  mục "AI Assistant"). Tầng "mini" cân bằng hiệu năng/chi phí cho chat có tool-calling (tầng
  "nano" rẻ hơn nhưng không đủ ổn định cho việc tự gọi tool nhiều vòng). **Bắt buộc** tự điền
  `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` thật vào `.env`
  (không commit) — thiếu thì `/assistant/*` trả `503`, các endpoint khác **không** bị ảnh hưởng.
  Resource Azure OpenAI tạo ở vùng khác (không phải East Asia) là đủ để né lỗi, không liên quan
  vùng của VM gọi đến nó.
- **Log là dữ liệu, không phải chỉ dẫn**: nội dung log đến từ client gọi `POST /ingest`, nên
  `service`, `signature`, `message` và `stack_trace` **không** nằm trong system prompt mà ở một
  message riêng, bọc trong thẻ `<untrusted_logs>`; system prompt nói rõ phần trong thẻ là dữ liệu
  để phân tích và không được làm theo yêu cầu xuất hiện trong đó. Chuỗi `</untrusted_logs>` xuất
  hiện trong log bị loại, nếu không một log soạn đúng cách sẽ thoát ra ngoài vùng dữ liệu. Thiệt
  hại nếu thiếu lớp này là **AI kết luận sai nguyên nhân theo ý kẻ tấn công** rồi người trực tin
  theo — các tool đều read-only nên không ghi/xoá được gì.
- **Ngưỡng báo động AI nói ra**: đọc từ `ANOMALY_THRESHOLD`, biến này phải được truyền cho **cả**
  `clustering` và `query-api` trong `docker-compose.yml`. Thiếu ở `query-api` thì AI vẫn nói ngưỡng
  `2.0` sau khi runbook đã hướng dẫn tăng lên `3.0`.
- **Theo dõi chi phí/độ trễ/token**: qua [Langfuse](https://jp.cloud.langfuse.com) — tự động,
  không cần đổi code gọi Azure OpenAI (dùng `langfuse.openai.OpenAI` trỏ `base_url` vào
  `<endpoint>/openai/v1/`). Để trống `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` thì assistant vẫn
  chạy bình thường, chỉ không gửi trace đi.
- **Lưu hội thoại**: 1 conversation/cụm, index `assistant-conversations` (xem
  [`assistant-conversation-schema.json`](../docs/architect/contracts/assistant-conversation-schema.json)).
  Mở lại Incident View vẫn thấy lại câu hỏi/trả lời cũ.
- **Bảo vệ chi phí**: `ASSISTANT_MAX_TOOL_ROUNDS` (mặc định 2) giới hạn số vòng AI tự gọi tool
  trong 1 lượt chat, tránh vòng lặp không điểm dừng. `ASSISTANT_MAX_HISTORY_MESSAGES` (mặc định
  20) chặn số message cũ gửi lại làm ngữ cảnh mỗi lượt — hội thoại vẫn lưu đầy đủ, chỉ phần gửi
  lên model bị cắt (nếu không, chi phí token tăng dần theo độ dài hội thoại).
- **Retention**: `ASSISTANT_RETENTION_DAYS` (mặc định 30) xoá hội thoại không được hỏi tiếp quá
  số ngày đó (theo `updated_at`). Job nền chạy mỗi `ASSISTANT_RETENTION_INTERVAL_SECONDS` giây;
  đặt `0` để tắt và chạy bằng cron ngoài: `python -m query-api.src.assistant.retention`.
- Hai route hội thoại `/assistant/clusters/*` được gắn `Depends(require_admin)` khi include router
  trong `main.py`, giống các query routes, vì đây là dữ liệu log/stack trace nội bộ và gọi API có
  phí. Riêng `GET /assistant/health` nằm ở router công khai (không token) để trang "Trạng thái hệ
  thống" đọc được — nó chỉ trả tình trạng cấu hình + kết quả lần gọi Azure OpenAI gần nhất, không
  chứa dữ liệu log/hội thoại và không gọi Azure OpenAI thật.

```bash
curl -X POST "http://localhost:8002/assistant/clusters/<cluster_id>/conversation/messages" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message": "Lỗi này do đâu, cách sửa thế nào?"}'
```

## AI Assistant — chất lượng đo được

Issue #108 đã có [bộ 20 câu và hướng dẫn chạy](tests/golden/README.md), script xác minh
cluster thật và [rubric/bảng chấm hai người](../docs/evidence/11-assistant-golden-set/README.md).
Bộ câu hỏi gồm 4 câu mỗi nhóm value/422, connection/502, timeout/504, runtime/500 và
bad_schema. Nhóm bad_schema kiểm tra việc AI nêu thiếu dữ liệu quarantine; chưa đo khả
năng điều tra quarantine trực tiếp.

Đã chạy đo thật trên bản deploy `38defc3` ngày **2026-11-20** (`gpt-5-mini`, reasoning effort
`low`, output cap 1200, ngữ cảnh đóng băng bằng cách stop `demo-app`). Cả hai lượt **20/20 câu,
0 lỗi API**, coverage telemetry **20/20**. Chi tiết và cách đo:
[measurement-nghia.md](../docs/evidence/11-assistant-golden-set/measurement-nghia.md).

| Chỉ số | `MAX_TOOL_ROUNDS=1` | `MAX_TOOL_ROUNDS=2` | Chênh |
|---|---|---|---|
| Điểm/60 (hai người chấm) | **pending** | **pending** | |
| Số câu lệch giữa hai người chấm | **pending** | **pending** | |
| Lần gọi model / câu | 1,0 | 1,2 (4/20 câu dùng vòng tool) | +4 lần |
| Token vào / câu | 1 059 | 1 714 | +61,8 % |
| Token ra / câu | 784 | 890 | +13,5 % |
| **Chi phí trung bình / câu** | **0,001718 USD** | **0,001979 USD** | **+15,2 %** |
| **Độ trễ p95 (model, Langfuse)** | **10,08 s** | **10,49 s** | +4,1 % |
| Độ trễ p95 (API đầu-cuối) | 10,11 s | 10,53 s | +4,2 % |

**Khuyến nghị: giữ `ASSISTANT_MAX_TOOL_ROUNDS = 2`** (tức giữ mặc định hiện tại). Giá phải trả là
+0,000261 USD/câu và +0,41 s ở p95; đổi lại, những câu cần dữ liệu ngoài 5 log mẫu chỉ trả lời
được ở cấu hình 2. Trên một cụm có trace còn sống, `rounds=2` nêu **đúng** HTTP status lấy từ
trace **2/2 lần**, `rounds=1` **0/2 lần**. `rounds=2` cũng không gây gọi tool tràn lan: 16/20 câu
vẫn trả lời thẳng từ log mẫu.

Lưu ý khi đọc hai cột trên: ở hai lượt chính, **cả 4 lần gọi `get_trace` đều trả `trace not
found`** vì 4 cụm golden có từ 2026-11-14 còn volume Badger của Jaeger mới tạo ở Task 10
(`BADGER_SPAN_STORE_TTL=168h`). Khuyến nghị ở trên dựa vào một **phép đo bổ sung** trên cụm có
trace sống, không dựa vào hai lượt đó. Hệ quả cần biết trước khi demo: `get_trace` luôn vô dụng
với cụm cũ hơn 7 ngày.

Ba dạng câu trả lời yếu nhất (bản đọc sơ bộ, chưa phải điểm chính thức): câu cần đọc trace/HTTP
status; câu mà mô hình tự mô tả sai năng lực của nó (`rounds=1` nói "không có quyền truy cập
tracing" dù hệ thống có tool `get_trace`); và câu về HTTP status nói chung — log của `demo-app`
không ghi `http.status_code` (span có, log không), nên thêm trường đó vào `metadata` lúc
`emit_log` sẽ đáng giá hơn mọi tinh chỉnh prompt. Nhóm `bad_schema` ngược lại trả lời **tốt**:
4/4 câu từ chối khẳng định đã có sự kiện quarantine và không bịa `trace_id`.

Điểm/60 còn **pending**: rubric đòi hai người thật chấm độc lập, bốn file `rater-*.csv` vẫn để
trống có chủ đích. PR không đổi cấu hình mặc định 2.

## Evidence sở hữu

- **Runbook**: [`../docs/task/runbook.md`](../docs/task/runbook.md)
- **Load test end-to-end**: `../load-tests/` — mô phỏng tải thật qua toàn bộ pipeline (ingest → cluster → alert → query)

### Mở rộng Search (đợt Minh)

- `GET /search` hỗ trợ `level=DEBUG|INFO|WARN|ERROR|FATAL` (lọc keyword).
- `GET /search/aggregations` (JWT admin): hỗ trợ bộ lọc như `/search`, thêm `interval=hour|day`; trả các bucket `histogram`, `levels`, `services`. Không sửa schema StructuredLog.
- Daily indices được đọc qua `OpenSearchLogStore.read_indices` gồm `logs` legacy + `logs-YYYY.MM.DD`; bản thân query-api không cần truy cập index cụ thể.
