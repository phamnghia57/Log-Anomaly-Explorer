# load-tests

Dùng chung giữa Minh (load test tầng ingestion) và Nghĩa (load test end-to-end). Công cụ: [Locust](https://locust.io/).

Hai nhóm người dùng trong [`locustfile.py`](locustfile.py):

| Nhóm | Mô phỏng | Request |
|---|---|---|
| `IngestionUser` | demo-app liên tục gửi log | `POST /ingest` — INFO (70%), ERROR kèm stack trace (30%), và log sai schema (kiểm tra đường quarantine, 400 được tính là **đúng**) |
| `QueryUser` | người dùng tra cứu + Incident View | `POST /auth/login` một lần/user, rồi `GET /search`, `GET /search` có filter, `GET /clusters`, `GET /clusters/{id}` (lấy `cluster_id` thật từ lần liệt kê trước, không bịa id) |

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

## Kết quả đo được (2026-10-23)

Evidence lịch sử trước khi bật JWT; không phải kết quả đo lại sau thay đổi authentication.

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
