# PR #117 — xử lý review ngày 19/11/2026

Base được kiểm tra: `96a8bf057391a42da16b02376ae4465b0159e009` trên `dev/namvk`.

| Mục | Kết quả |
|---|---|
| A1 | Fail-open chỉ với incident `StorageError`, có warning không chứa chi tiết exception; `RuntimeError` vẫn phát ra. Test worker xác nhận gửi alert và ghi cluster/history/heartbeat rồi đóng store bình thường. |
| A2 | Reset cờ lỗi webhook đầu mỗi chu kỳ; test failure/quiet/success, failure + 5 quiet và repeated failure. Success không ghi đè fail cùng chu kỳ. |
| B1 | Không tái hiện mismatch ở snapshot PR hiện tại: 03a, 03b, Git blob và generator chạy mới có cùng bytes/JSON/hash. README có bảng hash và artifact đối chiếu. |
| B2 | Runbook, BENCHMARK và README cảnh báo tắt ML cần ngưỡng 1.5; ghi số đo seed 98 và giới hạn synthetic. |
| B3 | README ghi ngưỡng Compose/.env.example là 3.0, phân biệt fallback Python không có env là 2.0. |
| B4 | Contract bổ sung signature/incident_url, null semantics và digest; runbook hướng dẫn link trực tiếp. Nội dung thông báo nhóm: [issue-101-comment.md](issue-101-comment.md). |
| C | [PR-description.md](PR-description.md): phạm vi sáu issue, first_anomaly_after, quyết định A1/A2, metric, Closes và gate evidence chưa đạt. |
| D local | [Live verification](../../evidence/02-history-sort/verify-live-history.txt): OpenSearch 2.17.1 thật trong container riêng; không dùng dữ liệu/email production. |
| D/E còn lại | Evidence triển khai vẫn thiếu, cần nhóm chốt người chạy; nội dung điều phối: [coordination-minh.md](coordination-minh.md). |

Regression: [125 passed](../../evidence/pr117-review/pytest-clustering.txt), Python 3.13.7.
Live verification dùng 150 timestamp synthetic, không thay thế ảnh UI của worker chạy >2 giờ.
Chưa chạy 10/50/100 ERROR/s hoặc đo ngưỡng lỡ cửa sổ. Chưa có email trước/sau,
stop/start → down/recovered, hoặc số đo disk VM. Không có cơ sở tuyên bố đóng đủ
acceptance cả sáu issue; danh sách `Closes` trong mô tả PR chỉ có hiệu lực khi merge.
Nhóm cần quyết định hoàn tất các gate trước merge hoặc tách follow-up được chấp thuận.
