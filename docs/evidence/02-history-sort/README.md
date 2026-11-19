# PR #117 — live storage verification

Output thật của lần chạy local: [verify-live-history.txt](verify-live-history.txt).
Script: `clustering/evaluation/verify_live_history.py`. Chạy từ root repo:

```sh
LIVE_TEST_OPENSEARCH_URL=http://127.0.0.1:19277 python -m clustering.evaluation.verify_live_history
```

Môi trường là OpenSearch 2.17.1 trong container Docker Desktop riêng, bind loopback,
2 CPU/2 GiB, heap 512 MiB. Không dùng index/volume ứng dụng. Script chỉ tạo index
tiền tố `codex-history-test-<uuid>`, luôn xóa các index test đã tạo trong `finally`.
Không cấu hình webhook/email thật; một lần gọi webhook ngoài dự kiến sẽ làm test fail.

Phạm vi kiểm tra:

- 150 điểm một phút synthetic, lấy đúng điểm 51–150 với `limit=100`, 101–150 với `limit=50`, thứ tự tăng dần.
- `since` gồm điểm tại mốc; retention xóa trước cutoff, giữ điểm tại cutoff và điểm của cluster khác.
- Heartbeat ghi được metric và incident acknowledged không phát webhook.

**Giới hạn:** 150 mốc thời gian được chèn vào storage, không phải worker đã chạy
liên tục 150 phút. Chưa có ảnh Incident View trước/sau trên bản deploy, nên chưa
đủ evidence UI của #97. #101 dùng chung output cho suppression trên storage thật;
#109 dùng cho cutoff storage, không thay thế số đo dung lượng VM.

Unit regression: [pytest-clustering.txt](../pr117-review/pytest-clustering.txt).
