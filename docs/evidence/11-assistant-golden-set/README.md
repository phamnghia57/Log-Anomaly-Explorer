# #108 — Assistant golden set: bàn giao phần Mạnh

**Trạng thái: xong.** Phần chạy đo: Nghĩa, 2026-11-20 — xem
[measurement-nghia.md](measurement-nghia.md). Phần chấm điểm: bản chấm của Codex (AI) ở
[ai-review/](ai-review/README.md) — rounds=1 **55/60** (17/20 câu đạt 3/3), rounds=2
**56/60** (18/20). Nhóm quyết định **không** chấm bằng hai người thật; đây là kết quả cuối,
và các bảng `rater-*.template.csv` / `adjudication.template.csv` được giữ lại nguyên trạng
làm template.

Đã kiểm kèm bản chấm: SHA-256 của 5 prepared artifact, các ID/binding, tổng điểm và Langfuse.
`connection-502-04` rỗng ở cả hai lượt (xác nhận từ Git blob gốc) nên mỗi lượt chỉ **19/20
câu có nội dung** dù vẫn 0 lỗi API; nguyên nhân rỗng không được xác nhận.

> Tài liệu dưới đây là bản bàn giao gốc của Mạnh, giữ nguyên để đối chiếu. Số thật về
> token/chi phí/độ trễ/coverage nằm trong [langfuse-summary.csv](langfuse-summary.csv) và
> [measurement-nghia.md](measurement-nghia.md).

## Đã chuẩn bị

- Catalog 20 câu tại [assistant-questions.json](../../../query-api/tests/golden/assistant-questions.json)
  và bản sao `questions.json` trong thư mục này; cả hai chưa gắn cluster ID (`null`).
- Bốn nhóm lỗi có cluster và bốn câu bad_schema kiểm tra giới hạn dữ liệu. Đáp án dựa trên
  `_inject_fault`/runbook; log/trace thật sẽ được kiểm tra khi bind.
- Script `prepare_assistant_golden.py` xác minh bốn ID thật, xuất câu hỏi đã bind cùng
  snapshot và SHA-256. Unit test dùng HTTP mock, không phải bằng chứng bản deploy.
- Bốn bảng `rater-*.template.csv` có 20 câu/bảng, ô điểm và danh tính để trống;
  `adjudication.template.csv` có 40 dòng; `summary.template.csv` chưa có số đo.
- [Rubric](RUBRIC.md) và [lệnh chạy trên VM](../../../query-api/tests/golden/README.md).

## Kiểm chứng offline đã chạy

Python 3.11.18, `cd query-api && python -m pytest -q -rs`: **386 passed, 7 skipped**.
Bảy test live storage bị skip vì chưa cấu hình `AUTH_TEST_OPENSEARCH_URL`; có một
Starlette/httpx deprecation warning từ dependency. Log đầy đủ ở
[validation/pytest-query-api.txt](validation/pytest-query-api.txt), metadata ở
[validation/summary.json](validation/summary.json).

CLI thực tế đã kiểm tra `--help` (exit 0), catalog chưa bind và mapping mẫu chưa điền
(đều exit 2, không tạo output); xem [cli-preflight.json](validation/cli-preflight.json).
Các kiểm tra binding thành công/sai fault/lỗi HTTP trong pytest dùng mock, không gọi
Azure/Langfuse. Đây là bằng chứng kiểm thử code, không thay thế số đo trên bản deploy.

`questions.json` trong thư mục này là catalog chưa bind; file đã chạy thật nằm ở
`prepared/questions.json` và manifest giữ hash của nó.
