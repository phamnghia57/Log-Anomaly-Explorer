# load-tests

Dùng chung giữa Minh (load test tầng ingestion) và Nghĩa (load test end-to-end). Công cụ: [Locust](https://locust.io/).

Hai nhóm người dùng trong [`locustfile.py`](locustfile.py):

| Nhóm | Mô phỏng | Request (kèm weight) |
|---|---|---|
| `IngestionUser` | demo-app liên tục gửi log | `POST /ingest` — INFO (7), ERROR kèm stack trace (3), log sai schema (1 — kiểm tra đường quarantine, 400 được tính là **đúng**); `POST /ingest/batch` (2 — mỗi request `LOAD_TEST_BATCH_SIZE` log, body là JSON **array**) |
| `QueryUser` | người dùng tra cứu + Dashboard + Incident View | `POST /auth/login` một lần/user, rồi `GET /search` (5), `GET /search` có filter (3), `GET /clusters` (3), `GET /clusters/{id}` (2 — lấy `cluster_id` thật từ lần liệt kê trước, không bịa id), `GET /search/aggregations` (2), `GET /clusters/{id}/history` (2), `PATCH /clusters/{id}` (1 — **mặc định tắt**) |

Hai điểm cần biết khi đọc kết quả của `QueryUser`:

- **`GET /clusters/{id}/history` là N request mỗi lần, không phải 1.** Mỗi card trên Dashboard tự
  gọi endpoint này cho riêng nó (xem `web/src/components/dashboard/ClusterCard.tsx`), nên một lần
  mở Dashboard bắn N request liên tiếp. Task `dashboard_sparklines` mô phỏng đúng hành vi đó với
  `LOAD_TEST_DASHBOARD_CARDS` cụm. Lưu ý `GET /clusters` mặc định trả tới **100** cụm, nên
  Dashboard thật có thể bắn tới 100 request — đây là đường nóng nhất của UI.
- **`PATCH /clusters/{id}` đổi trạng thái incident thật** nên mặc định không chạy. Bật bằng
  `LOAD_TEST_INCIDENT_WRITE=true` và chỉ bật trên môi trường được phép làm nhiễu dữ liệu demo:
  nó chuyển các đợt đang `open` thành `acknowledged`. Trong phép đo này **409 được tính là đúng**
  (nhiều user ảo cùng ack một cụm, hoặc đợt đã đổi trạng thái giữa lúc đọc và lúc ghi → CAS từ
  chối theo đúng thiết kế).

## Biến môi trường của load test

| Biến | Mặc định | Tác dụng |
|---|---|---|
| `INGESTION_HOST` | `http://localhost:8000` | Host của Ingestion |
| `QUERY_API_HOST` | `http://localhost:8002` | Host của Query API |
| `QUERY_API_USERNAME` / `QUERY_API_PASSWORD` | — | Bắt buộc với `QueryUser` (xem mục JWT) |
| `LOAD_TEST_BATCH_SIZE` | `50` | Số log mỗi `POST /ingest/batch` (server chặn ở `INGEST_MAX_BATCH_SIZE`, mặc định 500) |
| `LOAD_TEST_DASHBOARD_CARDS` | `12` | Số card Dashboard mô phỏng = số request `/clusters/{id}/history` mỗi lần |
| `LOAD_TEST_INCIDENT_WRITE` | tắt | `true` để bật `PATCH /clusters/{id}` (**ghi dữ liệu thật**) |

Log được sinh với **timestamp hiện tại** và nhiều loại lỗi khác nhau — nếu gắn mốc thời gian cố định thì log sẽ nằm ngoài cửa sổ 24h của `/search` lẫn cửa sổ đang xét của clustering, đo xong không quan sát được gì.

## Chạy

Các lệnh dưới đây chạy từ thư mục `load-tests/`. Với `QueryUser` hoặc chạy cả hai nhóm,
cần nạp credentials như mục JWT bên dưới trước khi bắt đầu. `IngestionUser` chạy riêng
không cần credentials Query API.

```bash
pip install locust

# Mac dinh: ingestion :8000, query-api :8002 tren cung may
locust -f locustfile.py

# Tro sang may chu khac / cong khac
INGESTION_HOST=http://<host>:8000 QUERY_API_HOST=http://<host>:8002 locust -f locustfile.py
```

Mở `http://localhost:8089`, nhập số user đồng thời và spawn rate theo mục tiêu đang cần đo.

Chạy riêng từng nhóm, hoặc chạy không cần giao diện để lấy CSV làm bằng chứng:

```bash
locust -f locustfile.py IngestionUser          # chi tang ingestion
locust -f locustfile.py QueryUser              # chi doc qua query-api

locust -f locustfile.py --headless --users 50 --spawn-rate 5 --run-time 3m \
       --csv ket-qua-load-test
```

## JWT cho QueryUser

Query API bảo vệ `/search`, `/clusters` và `/clusters/{cluster_id}` bằng JWT admin.
Request không có Bearer token trả 401. Dùng tài khoản admin đã seed trong OpenSearch,
theo [`query-api/README.md`](../query-api/README.md); load test không tự seed hoặc đăng ký user.

Mỗi simulated user khởi tạo `cluster_ids`, đọc `QUERY_API_USERNAME`/`QUERY_API_PASSWORD`
từ environment và gửi JSON tới `/auth/login` bằng Locust client trong `on_start()`.
Sau response 200 có JWT đúng dạng, client lưu `Authorization: Bearer <token>` trong
`self.client.headers`, nên mọi task GET sau đó tự mang token. Không login lại trong task;
weights, wait times và việc chọn cluster ID thật giữ nguyên.

Ví dụ Bash, nhập credentials bằng prompt để password không nằm trong shell history:

```bash
read -r -p "Seeded admin username: " QUERY_API_USERNAME
read -r -s -p "Seeded admin password: " QUERY_API_PASSWORD
printf '\n'
export QUERY_API_USERNAME QUERY_API_PASSWORD
export QUERY_API_HOST=http://localhost:8002
locust -f locustfile.py QueryUser --headless --users 50 --spawn-rate 5 --run-time 3m \
       --csv ket-qua-load-test
unset QUERY_API_USERNAME QUERY_API_PASSWORD
```

Ví dụ PowerShell, dùng prompt credentials:

```powershell
$queryApiCredential = Get-Credential -Message "Seeded Query API admin"
$env:QUERY_API_USERNAME = $queryApiCredential.UserName
$env:QUERY_API_PASSWORD = $queryApiCredential.GetNetworkCredential().Password
$env:QUERY_API_HOST = "http://localhost:8002"
locust -f locustfile.py QueryUser --headless --users 50 --spawn-rate 5 --run-time 3m `
       --csv ket-qua-load-test
Remove-Item Env:QUERY_API_USERNAME, Env:QUERY_API_PASSWORD
$queryApiCredential = $null
```

Bỏ `--headless`/các cờ tải để dùng UI tại `http://localhost:8089`. Bỏ `QueryUser` để chạy
cả ingestion và query (vẫn cần credentials). Với host từ xa dùng HTTPS; không đưa password
vào command arguments, Git, ảnh hoặc log. Script đọc environment, không tự đọc `.env`;
không cần và không cấp `JWT_SECRET` cho Locust. Backend chịu trách nhiệm ký/verify JWT.

Thiếu/rỗng credentials: báo tên biến cần cấu hình và dừng simulated user trước mọi HTTP
request. Login không trả 200, lỗi mạng, JSON hỏng hoặc thiếu/JWT sai dạng: login được đánh
dấu failure và user dừng, không chạy tiếp các GET thiếu token. Không in credentials, JWT
hoặc response body vào thông báo lỗi.

Kiểm tra Locust Statistics/Failures: phải thấy dòng **`POST /auth/login`** thành công cho
mỗi user đã khởi động; các GET bảo vệ xuất hiện sau login và không có lỗi 401 do thiếu
header. Nếu login failure, kiểm tra tài khoản đã seed, host và cấu hình JWT backend; nếu
không có request nào, đọc log để phát hiện thiếu biến môi trường. Login góp vào tổng
request/latency khi spawn user, nên tách dòng này khi đánh giá tải query ổn định.

Token chỉ lấy một lần/user, chưa tự refresh/re-login khi hết hạn. Giữ thời gian chạy ngắn
hơn lifetime còn lại (`JWT_EXPIRY_SECONDS`, mặc định 3600 giây); 401 sau expiry là lỗi auth
thật và vẫn được thống kê, không bị đổi thành success. Không tăng lifetime production
chỉ để chạy load test; dùng môi trường test được phép.

## Kiểm tra tự động không cần backend

```bash
python -m pip install locust pytest
python -m pytest -q tests
python -m locust -f locustfile.py --list
```

Tests dùng Locust HttpSession/events thật và mock requests transport: login trước task,
header được dùng lại trên mọi endpoint, mỗi user có token riêng, login failure vẫn có
statistics, thiếu/sai credentials, JSON/JWT hỏng và lỗi mạng dừng user. Không phải phép đo
tải với API/OpenSearch thật; chỉ ghi live load-test evidence khi thực sự chạy với backend.

## Evidence cần ghi lại

- Throughput (request/giây) tại các mức tải khác nhau
- Tỷ lệ lỗi / timeout khi tải tăng
- Độ trễ p95/p99, tách riêng từng endpoint — đặc biệt `GET /clusters/{id}` vì đây là request nặng nhất (đọc cụm rồi kéo toàn bộ log gốc theo `log_ids`)
- Lưu file `*_stats.csv` của Locust (hoặc screenshot) vào thư mục này để làm bằng chứng

## Lưu ý khi đọc kết quả

- `POST /ingest (sai schema)` trả **400 là đúng** — đã được đánh dấu `success` trong locustfile, không tính vào tỷ lệ lỗi.
- `GET /clusters/{id}` chỉ bắt đầu chạy sau khi `GET /clusters` trả về cụm đầu tiên. Lúc mới khởi động, clustering chưa chạy xong chu kỳ nào nên endpoint này tạm thời không có request — đó là bình thường, không phải lỗi.

## Cách đo lại

Evidence đang dùng đo ngày **2026-11-13** ở **một mức tải** (20 user) — xem mục ngay dưới.
Còn thiếu mức **10 và 50 user** để thấy điểm bắt đầu xuống cấp. Phải đo lại mỗi khi backend
đổi thứ nằm trên đường request (auth, storage, endpoint mới): số của bản cũ không dùng lại
được — bảng 2026-10-23 ở cuối file là ví dụ, đo trước khi bật JWT nên chỉ còn giá trị so sánh
xu hướng.

Chạy trên **đúng máy chủ deploy** (2 vCPU/4GB chạy chung OpenSearch + Jaeger + clustering —
đo ở máy khác thì không so sánh được), qua cổng nội bộ, không qua gateway:

```bash
cd load-tests
pip install locust

read -r -p "Seeded admin username: " QUERY_API_USERNAME
read -r -s -p "Seeded admin password: " QUERY_API_PASSWORD; printf '\n'
export QUERY_API_USERNAME QUERY_API_PASSWORD
export INGESTION_HOST=http://localhost:9000 QUERY_API_HOST=http://localhost:9002

for u in 10 20 50; do
  locust -f locustfile.py --headless --users "$u" --spawn-rate 1 --run-time 3m \
         --csv "ket-qua-load-test-${u}u"
  sleep 330
done

unset QUERY_API_USERNAME QUERY_API_PASSWORD
```

Đổi `9000`/`9002` theo `INGESTION_PORT`/`QUERY_API_PORT` trong `.env` của máy chủ. Mỗi mức tải
sinh ra `ket-qua-load-test-<N>u_stats.csv` — commit file vào thư mục này rồi cập nhật bảng
tóm tắt bên dưới (ghi rõ ngày đo và mức tải). Lưu ý `GET /clusters/{id}` và
`GET /clusters/{id}/history` chỉ có request sau khi clustering đã chạy xong ít nhất một chu kỳ,
nên để hệ thống chạy vài phút trước khi đo.

**`--spawn-rate 1` và `sleep 330` không phải cho máy nghỉ.** Mọi simulated user dùng chung một
tài khoản admin, mà rate-limit login là **5 lần/tài khoản trong 300 giây**, chạm ngưỡng thì khoá
thêm 300 giây (`AUTH_LOGIN_MAX_ATTEMPTS`/`AUTH_LOGIN_WINDOW_SECONDS`, xem
`query-api/src/login_limits.py`). Login thành công tự giải phóng budget, nhưng chỉ **sau** khi
verify Argon2id xong (~160ms, xem bảng dưới), nên spawn nhanh làm nhiều login chồng nhau và
user thứ 6 ăn 429 — khoá luôn cả đăng nhập web trong 5 phút. Spawn 1 user/giây thì không chồng.
Nếu `*_failures.csv` vẫn có 429: chờ 5 phút, tạm đặt `AUTH_LOGIN_MAX_ATTEMPTS` cao trong `.env`
của máy chủ, recreate `query-api`, đo xong trả lại giá trị cũ — và ghi rõ trong bảng là phép đo
chạy với giới hạn đã nới.

## Kết quả đo được (2026-11-13, 20 user) — evidence hiện hành

Chạy thật trên máy chủ deploy (2 vCPU / 4GB, chạy chung với OpenSearch + Jaeger +
`clustering`), qua cổng nội bộ, không qua gateway. Bản backend đã có JWT + refresh/revocation,
rate-limit đăng nhập, `logs` phân trang, daily indices và AI Assistant:

```bash
locust -f locustfile.py --headless --users 20 --spawn-rate 1 --run-time 3m \
       --csv ket-qua-load-test-20u
```

20 user được Locust chia đều cho hai nhóm: 10 `IngestionUser` + 10 `QueryUser`.
File gốc: [`ket-qua-load-test-20u_stats.csv`](ket-qua-load-test-20u_stats.csv). Tóm tắt:

| Endpoint | Request | Lỗi | Req/s | Median | p95 | p99 | Max |
|---|---|---|---|---|---|---|---|
| `POST /ingest` (INFO) | 2950 | 0 | 16.46 | 8 ms | 18 ms | 30 ms | 137 ms |
| `POST /ingest` (ERROR) | 1215 | 0 | 6.78 | 8 ms | 19 ms | 28 ms | 280 ms |
| `POST /ingest` (sai schema) | 445 | 0 | 2.48 | 8 ms | 16 ms | 25 ms | 44 ms |
| `POST /ingest/batch` (50 log) | 851 | 0 | 4.75 | 15 ms | 31 ms | 46 ms | 90 ms |
| `GET /search` | 396 | 0 | 2.21 | 12 ms | 30 ms | 47 ms | 72 ms |
| `GET /search` (có filter) | 197 | 0 | 1.10 | 7 ms | 19 ms | 45 ms | 48 ms |
| `GET /search/aggregations` | 129 | 0 | 0.72 | 14 ms | 34 ms | 48 ms | 60 ms |
| `GET /clusters` | 227 | 0 | 1.27 | 8 ms | 22 ms | 32 ms | 33 ms |
| `GET /clusters/{id}` | 166 | 0 | 0.93 | 12 ms | 32 ms | 52 ms | 79 ms |
| `GET /clusters/{id}/history` | 1573 | 0 | 8.78 | 7 ms | 16 ms | 26 ms | 91 ms |
| `POST /auth/login` | 10 | 0 | 0.06 | **160 ms** | 260 ms | 260 ms | 265 ms |
| **Tổng** | **8159** | **0** | **45.52** | 9 ms | 22 ms | 36 ms | 280 ms |

**Nhận xét**:
- **0 lỗi trên toàn bộ 8159 request** ở 20 user đồng thời, gồm 10/10 login thành công — không
  có 403 (CSRF) lẫn 429 (rate-limit). Throughput tổng 45.5 req/s, cao hơn mức 37.1 req/s của
  lần 23/10 dù mỗi request đọc giờ phải verify JWT.
- **`POST /auth/login` là request chậm nhất hệ thống** (median 160ms, ~20 lần endpoint đọc
  trung bình). Đây là **đúng thiết kế**, không phải vấn đề hiệu năng: Argon2id cố tình tốn CPU
  để chống brute-force. Mỗi user chỉ login một lần nên nó không ảnh hưởng tải đọc — khi đánh
  giá tầng đọc phải tách riêng dòng này.
- **`GET /clusters/{id}/history` là đường nóng nhất của tầng đọc**: 1573 request / 8.78 req/s,
  gấp ~7 lần `GET /clusters`, đúng như cảnh báo ở đầu file (mỗi lần mở Dashboard bắn N request,
  một cho mỗi card). Nó vẫn rẻ (median 7ms) nhưng là endpoint cần theo dõi đầu tiên khi tăng
  số card hoặc số cụm.
- **`GET /clusters/{id}` không còn là endpoint chậm nhất** như kết luận ngày 23/10: median
  530ms → 12ms, p99 1.7s → 52ms. **Chưa xác định được nguyên nhân chắc chắn**, có hai ứng viên
  và phép đo này không tách được chúng: (a) `logs` giờ được phân trang (`logs_limit` mặc định
  100, `query-api/src/main.py`) nên không còn `mget` toàn bộ log của cụm — nhưng chỉ ảnh hưởng
  cụm có hơn 100 log; (b) lượng dữ liệu trong OpenSearch và kích thước cụm lúc đo hai lần khác
  nhau, không kiểm soát được. Không nên ghi "đã tối ưu xong" ở đâu dựa trên con số này.
  Nó vẫn là endpoint đọc có đuôi dài nhất (p99 52ms, max 79ms).
- Phương pháp khác lần 23/10 ở hai điểm, cần biết khi so: lần này **3 phút / spawn-rate 1**,
  lần trước **2 phút / spawn-rate 2**. Spawn chậm hơn là bắt buộc vì rate-limit login (xem mục
  trên); thời gian dài hơn cho số ổn định hơn. Throughput và percentile tính theo tỉ lệ nên vẫn
  so sánh được.
- **Chưa đo mức 10 và 50 user**, nên chưa biết điểm bắt đầu xuống cấp. Ở 20 user hệ thống còn
  rất thoải mái (p99 toàn hệ thống 36ms), chưa thấy dấu hiệu bão hoà.

## Kết quả đo được (2026-10-23) — evidence lịch sử, đã lỗi thời

Đo **trước khi bật JWT** và trước các endpoint mới; giữ lại để so sánh xu hướng, không dùng làm
evidence cho bản hiện tại (xem mục trên).

Chạy thật trên máy chủ deploy (2 vCPU / 4GB, chạy chung với OpenSearch + Jaeger +
`clustering`), qua cổng nội bộ (`localhost:8000`/`:8002`, không qua gateway):

```bash
locust -f locustfile.py --headless --users 20 --spawn-rate 2 --run-time 2m \
       --csv ket-qua-load-test
```

File gốc: [`ket-qua-load-test_stats.csv`](ket-qua-load-test_stats.csv). Tóm tắt:

| Endpoint | Request | Lỗi | Req/s | Median | p95 | p99 | Max |
|---|---|---|---|---|---|---|---|
| `POST /ingest` (INFO) | 2285 | 0 | 19.17 | 11 ms | 24 ms | 53 ms | 110 ms |
| `POST /ingest` (ERROR) | 1032 | 0 | 8.66 | 11 ms | 26 ms | 50 ms | 100 ms |
| `POST /ingest` (sai schema) | 328 | 0 | 2.75 | 11 ms | 27 ms | 68 ms | 215 ms |
| `GET /search` | 297 | 0 | 2.49 | 55 ms | 300 ms | 650 ms | 990 ms |
| `GET /search` (có filter) | 174 | 0 | 1.46 | 8 ms | 180 ms | 750 ms | 1048 ms |
| `GET /clusters` | 191 | 0 | 1.60 | 190 ms | 450 ms | 1100 ms | 1127 ms |
| `GET /clusters/{id}` | 119 | 0 | 1.00 | **530 ms** | 1200 ms | 1700 ms | 1841 ms |
| **Tổng** | **4426** | **0** | **37.12** | 12 ms | 230 ms | 750 ms | 1841 ms |

**Nhận xét**:
- **0 lỗi** trên toàn bộ 4426 request ở mức 20 user đồng thời — ổn định ở tải này.
- Tầng ghi (`/ingest`) nhanh và ổn định hơn hẳn tầng đọc (median 11ms so với 55-530ms) — đúng
  bản chất: ghi là `index()` đơn giản, đọc phải query/aggregate qua OpenSearch.
- **`GET /clusters/{id}` (Incident View) là endpoint chậm nhất rõ rệt** (median 530ms, p99
  1.7s, max gần 1.9s) — vì phải `get_logs(log_ids)` (mget) toàn bộ log gốc của cụm, cụm càng
  nhiều log thì càng chậm (ví dụ cụm 40 log trong lần test thủ công trước đó). Đáng lưu ý nếu
  sau này có cụm lên tới hàng trăm log — có thể cần phân trang `logs` thay vì trả hết một lần.
- `GET /search` (có filter) trong `locustfile.py` dùng **cả** `service` lẫn `q="failed"` (không
  phải chỉ lọc field chính xác) — median thấp hơn bản không filter (8ms so với 55ms) nhiều khả
  năng vì bộ lọc thu hẹp số log khớp cần tính điểm/sắp xếp, không phải do khác loại truy vấn.
  Đuôi phân phối (p99 750ms, cao hơn bản không filter) đáng chú ý nhưng chưa đủ dữ liệu để kết
  luận nguyên nhân chắc chắn — cần đo thêm với nhiều mức tải khác nhau mới nên kết luận.
