PR #117 cập nhật contract Alert theo hướng chỉ thêm field: `signature` (mẫu lỗi chuẩn hóa, chuỗi rỗng với record cũ) và `incident_url` (link frontend `/clusters/{URL-encoded cluster_id}`, `null` khi chưa cấu hình `ALERT_WEB_BASE_URL`). Các field cũ và top-level của alert đầu tiên trong digest được giữ để tương thích consumer hiện có.

Incident acknowledged được bỏ gửi. Nếu đọc incident gặp `StorageError`, worker ghi cảnh báo và vẫn xét gửi theo ngưỡng/cooldown, đúng yêu cầu fail-open của #101; không che lỗi lập trình khác. Có test alert và test worker chứng minh cluster/history/heartbeat vẫn được ghi khi phần còn lại thành công.

Runbook đã hướng dẫn bấm `incident_url` trong email; chưa cấu hình URL mới cần tìm cluster theo ID. Nhờ Nghĩa và nhóm xác nhận contract/Make.com trước merge. Evidence email thật và bảng đếm bước tới stack trace vẫn cần môi trường webhook của nhóm; chưa coi payload test hoặc kiểm chứng OpenSearch local là evidence email.
