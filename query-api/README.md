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
| `GET /clusters/{id}` | `logs_limit`, `logs_offset` | Incident View: cụm + `logs` tra từ `log_ids`, **có phân trang** (`logs_total` = tổng số log của cụm) |
| `GET /clusters/{id}/history` | `since`, `limit` | Xu hướng anomaly score theo thời gian (index `cluster-history`) |
| `GET /metrics` | — | Metrics dạng Prometheus, **không** route ra Internet qua gateway |

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

## Chuẩn bị cấu hình JWT admin

`src/config.py` đọc cấu hình auth từ environment khi import, theo cách cấu hình hiện có
của ingestion. User repository dùng client từ `ingestion.src.storage.build_store()` hoặc
`OpenSearchLogStore` truyền vào, giữ nguyên URL, credentials, TLS, timeout và shard settings
hiện có. User dùng index riêng trên cùng OpenSearch theo `users-schema.json`.

- `JWT_SECRET`: không có mặc định. `require_jwt_secret()` báo lỗi khi thiếu, rỗng hoặc
  chỉ có khoảng trắng; code authentication ở bước sau phải gọi hàm này trước khi dùng JWT.
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
Admin mới có `username`, `password_hash`, `role="admin"`, `created_at` UTC; `last_login_at`
chưa được ghi vì chưa có login. Document `_id` chính là username. Password được hash
bằng [argon2-cffi PasswordHasher](https://argon2-cffi.readthedocs.io/en/stable/howto.html)
(Argon2id, salt ngẫu nhiên); chỉ hash được lưu trong `_source`, không index hash để tìm kiếm.

Chỉ lệnh trên mới seed; không tự chạy khi API khởi động. Nếu account đã tồn tại, lệnh
báo `Existing account preserved; no changes made.` và giữ nguyên hash, role, timestamps,
kể cả khi environment chứa password mới. Ghi bằng OpenSearch `_create` để hai tiến trình
seed đồng thời cũng không ghi đè nhau. Đây không phải lệnh reset/rotate password.

Exit code `0`: tạo mới hoặc giữ account hiện có. Exit code `1`: thiếu credentials,
backend không hợp lệ, lỗi hashing hoặc OpenSearch; thông báo không in password/chi tiết
response. Thiếu credentials được kiểm tra trước mọi thao tác storage. Seed không phát JWT
nên không yêu cầu `JWT_SECRET`; authentication ở bước sau vẫn bắt buộc có secret riêng.

Chạy tests từ `query-api/`: `python -m pytest -q`. Tests dùng OpenSearch mock và Argon2
thật, kiểm tra schema, create-only, seed lặp, bảo toàn account cũ, race conditions, cấu hình
thiếu, lỗi storage, cleanup và thông báo CLI không chứa password. Không cần live cluster.

Bước này chưa thêm login, public registration, phát/kiểm tra JWT hay bảo vệ route.
Không có thay đổi frontend hoặc frozen contracts.

## Evidence sở hữu

- **Runbook**: [`../docs/task/runbook.md`](../docs/task/runbook.md)
- **Load test end-to-end**: `../load-tests/` — mô phỏng tải thật qua toàn bộ pipeline (ingest → cluster → alert → query)
