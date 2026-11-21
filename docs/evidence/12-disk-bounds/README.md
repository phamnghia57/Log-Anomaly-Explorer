# PR #117 — cluster-history retention evidence

[verify-live-history.txt](../02-history-sort/verify-live-history.txt) kiểm tra
delete-by-query trên OpenSearch local: xóa điểm trước cutoff, giữ điểm tại/sau
cutoff và giữ dữ liệu cluster khác. Test chạy trên index test có tiền tố riêng,
không đo hay xóa dữ liệu ứng dụng. Unit regression và guard chặn index pattern:
[pytest-clustering.txt](../pr117-review/pytest-clustering.txt).

Dung lượng trên VM chỉ có bản **sau** deploy: [df-h-sau-deploy.txt](df-h-sau-deploy.txt)
(29 G, dùng 12 G, còn 17 G — 42 %) và [cat-indices-sau-deploy.txt](cat-indices-sau-deploy.txt).
Không có bản "trước" đo từ VM. Delete-by-query cũng có thể chưa giảm dung lượng
ngay vì segment/merge; không suy ra disk đã giảm chỉ từ số document deleted.

Phần log rotation Docker thuộc Nghĩa: xem [logging-driver.md](logging-driver.md)
— bản sửa `docker-compose.yml`, trạng thái **trước** khi sửa
([logconfig-truoc.txt](logconfig-truoc.txt), mọi container đang không có trần
kích thước log), trạng thái **sau** khi deploy
([logconfig-sau.txt](logconfig-sau.txt), 8/8 container đạt `max-size=10m
max-file=3`, log tụt 4,8 MB → 436 KB) và số điểm history sẽ bị xoá theo từng
cutoff ([retention-count.txt](retention-count.txt)). Sinh lại bằng
[verify-logging.sh](verify-logging.sh).

## Quarantine retention (Minh)

Trước đây `logs-quarantine` (445 document lúc đo 20/11) không có cơ chế nào xoá:
`_drop_daily_indices` cố ý chỉ khớp `logs-YYYY.MM.DD`, và từ PR #127 snapshot
(`-logs-*`) cũng loại nó — không trần đĩa, không bản sao.

Quyết định: **thêm `delete_by_query` theo tuổi vào retention**, KHÔNG đổi tên
index. Lý do: log sai schema chỉ cần để debug gần đây, không cần khôi phục sau
sự cố, nên để ngoài snapshot là đúng; đổi tên index sẽ phải migrate 445 document,
sửa `read_indices`, `QUARANTINE_INDEX` trên VM và pattern backup cùng lúc.

- Code: `OpenSearchLogStore.delete_quarantine_older_than` (`range received_at <
  cutoff`, `conflicts=proceed`, `failures` → `StorageError`), gọi từ
  `retention.run_all` mỗi `RETENTION_INTERVAL_SECONDS`. Số ngày:
  `QUARANTINE_RETENTION_DAYS` (compose mặc định 30).
- Test: `ingestion/tests/test_quarantine_retention.py` (không đụng index log
  chính, tên index cấu hình được, lỗi một phần không im lặng).
- Đo trên VM: [quarantine-retention.sh](quarantine-retention.sh) in `_count`
  **trước/sau** một lượt. Với 30 ngày, dữ liệu hiện tại (từ đầu tháng 11) chưa có
  document nào quá hạn → `deleted=0` là kết quả đúng; muốn thấy cơ chế thật thì
  `--dry-run` trước, rồi `DAYS=<n>` đủ nhỏ để `_count received_at<cutoff` > 0.

Kết quả history local không đóng toàn bộ acceptance của #109.
