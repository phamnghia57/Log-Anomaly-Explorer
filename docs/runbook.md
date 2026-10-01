# Runbook — Log Anomaly Explorer

> Sở hữu: Nghĩa (nhóm trưởng). Điền dần khi hệ thống đã chạy thật; đây là khung bắt buộc cho GitHub evidence "runbook".

## Khi nhận được Alert

1. **Nhận alert** (webhook/email) — nội dung gồm `cluster_id`, `score`, `service`, `first_seen`.
2. **Mở Incident View**: `GET /clusters/{cluster_id}` để xem chi tiết cụm, danh sách log liên quan.
3. **Lần theo trace/request**: dùng `trace_ids` trong response để xác định request cụ thể đã gây lỗi.
4. **Xác định phạm vi ảnh hưởng**: service nào, từ khi nào (`first_seen` → `last_seen`), bao nhiêu log liên quan.
5. **Hành động**:
   - [ ] TODO: điền quy trình xử lý cụ thể theo từng nhóm lỗi (vd. rollback, restart service, liên hệ đối tác tích hợp nếu lỗi ở tầng API)
6. **Đóng sự cố**: cập nhật trạng thái cụm, ghi chú nguyên nhân gốc (root cause) để làm dữ liệu cho `labeled_incidents` (Nam dùng để đo precision/recall).

## Khi hệ thống báo động giả (false positive) nhiều

- [ ] TODO: quy trình điều chỉnh ngưỡng anomaly score, phối hợp với Nam.

## Khi Ingestion quá tải / rớt log

- [ ] TODO: quy trình kiểm tra load test (`load-tests/`), phối hợp với Minh.

## Liên hệ

| Module | Phụ trách |
|---|---|
| Demo app / Fault injection | Mạnh |
| Ingestion / Storage | Minh |
| Clustering / Anomaly score / Alert | Nam |
| Search / Incident View / Tích hợp | Nghĩa |
