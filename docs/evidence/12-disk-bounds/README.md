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
- Evidence trên VM: chạy [quarantine-retention.sh](quarantine-retention.sh) →
  `quarantine-retention.txt` có `_count` **trước/sau**. Với 30 ngày, dữ liệu
  hiện tại (từ đầu tháng 11) có thể chưa có document nào quá hạn → `deleted=0`
  vẫn là kết quả hợp lệ, nhưng để thấy cơ chế thật thì chạy `--dry-run` trước,
  rồi `DAYS=<n>` với n đủ nhỏ để `_count received_at<cutoff` > 0.

| Mục | Giá trị |
|---|---|
| `_count` tổng trước | điền |
| `_count received_at < cutoff` trước | điền |
| `deleted` | điền |
| `_count` tổng sau | điền |
| `_count received_at < cutoff` sau (phải = 0) | điền |
| `QUARANTINE_RETENTION_DAYS` / `DAYS` dùng | điền |

Kết quả history local không đóng toàn bộ acceptance của #109.
