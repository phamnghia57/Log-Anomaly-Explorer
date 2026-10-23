# load-tests

Dùng chung giữa Minh (load test tầng ingestion) và Nghĩa (load test end-to-end). Công cụ: [Locust](https://locust.io/).

Hai nhóm người dùng trong [`locustfile.py`](locustfile.py):

| Nhóm | Mô phỏng | Request |
|---|---|---|
| `IngestionUser` | demo-app liên tục gửi log | `POST /ingest` — INFO (70%), ERROR kèm stack trace (30%), và log sai schema (kiểm tra đường quarantine, 400 được tính là **đúng**) |
| `QueryUser` | người dùng tra cứu + Incident View | `GET /search`, `GET /search` có filter, `GET /clusters`, `GET /clusters/{id}` (lấy `cluster_id` thật từ lần liệt kê trước, không bịa id) |

Log được sinh với **timestamp hiện tại** và nhiều loại lỗi khác nhau — nếu gắn mốc thời gian cố định thì log sẽ nằm ngoài cửa sổ 24h của `/search` lẫn cửa sổ đang xét của clustering, đo xong không quan sát được gì.

## Chạy

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

## Evidence cần ghi lại

- Throughput (request/giây) tại các mức tải khác nhau
- Tỷ lệ lỗi / timeout khi tải tăng
- Độ trễ p95/p99, tách riêng từng endpoint — đặc biệt `GET /clusters/{id}` vì đây là request nặng nhất (đọc cụm rồi kéo toàn bộ log gốc theo `log_ids`)
- Lưu file `*_stats.csv` của Locust (hoặc screenshot) vào thư mục này để làm bằng chứng

## Lưu ý khi đọc kết quả

- `POST /ingest (sai schema)` trả **400 là đúng** — đã được đánh dấu `success` trong locustfile, không tính vào tỷ lệ lỗi.
- `GET /clusters/{id}` chỉ bắt đầu chạy sau khi `GET /clusters` trả về cụm đầu tiên. Lúc mới khởi động, clustering chưa chạy xong chu kỳ nào nên endpoint này tạm thời không có request — đó là bình thường, không phải lỗi.

## Kết quả đo được (2026-10-23)

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
