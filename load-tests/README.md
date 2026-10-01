# load-tests

Dùng chung giữa Minh (load test tầng ingestion) và Nghĩa (load test end-to-end). Công cụ: [Locust](https://locust.io/).

## Chạy thử

```bash
pip install locust
locust -f locustfile.py
```

Mở `http://localhost:8089`, nhập số user đồng thời và spawn rate theo mục tiêu đang cần đo (ví dụ: theo tham số người dùng đồng thời của một biến thể cá nhân hoá cụ thể, hoặc theo mục tiêu chung cả nhóm thống nhất).

## Evidence cần ghi lại

- Throughput (request/giây) tại các mức tải khác nhau
- Tỷ lệ lỗi / timeout khi tải tăng
- Với `QueryUser`: độ trễ p95/p99 khi `/clusters` bị gọi đồng thời
- Lưu kết quả (CSV/screenshot Locust) vào thư mục này hoặc đính kèm vào PR làm bằng chứng
