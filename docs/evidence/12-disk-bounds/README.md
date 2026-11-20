# PR #117 — cluster-history retention evidence

[verify-live-history.txt](../02-history-sort/verify-live-history.txt) kiểm tra
delete-by-query trên OpenSearch local: xóa điểm trước cutoff, giữ điểm tại/sau
cutoff và giữ dữ liệu cluster khác. Test chạy trên index test có tiền tố riêng,
không đo hay xóa dữ liệu ứng dụng. Unit regression và guard chặn index pattern:
[pytest-clustering.txt](../pr117-review/pytest-clustering.txt).

Chưa có evidence disk trên VM: cần `df-h-before.txt`, `df-h-after.txt`,
`cat-indices-before.txt`, `cat-indices-after.txt` với
`_cat/indices?v&s=store.size:desc`, timestamp/cutoff và output retention.
Delete-by-query có thể chưa giảm dung lượng ngay vì segment/merge; không suy ra
disk đã giảm chỉ từ số document deleted.

Phần log rotation Docker thuộc Nghĩa: xem [logging-driver.md](logging-driver.md)
— đã có bản sửa `docker-compose.yml` + trạng thái **trước** khi sửa
([logconfig-truoc.txt](logconfig-truoc.txt), xác nhận mọi container đang không
có trần kích thước log) + số điểm history sẽ bị xoá theo từng cutoff
([retention-count.txt](retention-count.txt)). Phần xác minh sau khi deploy còn
trống, chạy [verify-logging.sh](verify-logging.sh) để điền.

Quarantine retention thuộc Minh, chưa làm: `logs-quarantine` đang có 445
document và không có cơ chế nào xoá. Kết quả history local không đóng toàn bộ
acceptance của #109.
