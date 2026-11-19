# PR #117 — actionable alert evidence

Unit regression: [pytest-clustering.txt](../pr117-review/pytest-clustering.txt).
Incident acknowledged trên OpenSearch thật:
[verify-live-history.txt](../02-history-sort/verify-live-history.txt).

Đã kiểm tra payload có signature/link URL-encode, thiếu base URL thì link null,
suppression cho acknowledged và fail-open có cảnh báo khi đọc incident gặp
StorageError. Không có email/Make.com thật trong các test này.

Trước khi nghiệm thu #101, người có quyền webhook cần lưu ảnh email trước/sau,
che thông tin riêng tư, và đếm số thao tác thực từ email đến stack trace.
`incident_url` đưa tới Incident View, không tự mở hộp thoại stack trace; số thao
tác còn phụ thuộc trạng thái đăng nhập và thao tác chọn log. Chưa đo thì không
tuyên bố email → stack trace chỉ còn một click.

Thông báo contract chuẩn bị tại
`docs/task/pr117-review/issue-101-comment.md`; cần nhóm xác nhận trước merge.
