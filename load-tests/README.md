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
