# #108 — Assistant golden set: bàn giao phần Mạnh

**Trạng thái: chuẩn bị câu hỏi/quy trình; chưa có kết quả runtime hoặc chấm điểm.**

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

## Nghĩa chạy đo, hai người chấm hoàn thiện

- [ ] Điền mapping bốn ID thật, chạy script prepare trên VM; lưu `prepared/` với manifest
  và snapshot. Đây là bước xác minh runtime đầu tiên; chưa có bản prepared được commit.
- [ ] Giữ ngữ cảnh ổn định, ghi config/env server thực tế, Git SHA/image, deployment,
  reasoning effort, output cap, timeout, tool khả dụng và thời điểm UTC.
- [ ] Chạy cùng `prepared/questions.json` với MAX_TOOL_ROUNDS=1 và =2, mặc định delay 10s;
  giữ `scores-round1.csv`, `scores-round2.csv` thô và console log/cửa sổ UTC mỗi lượt.
- [ ] Xuất Langfuse thô, ghép generation theo câu, xuất `langfuse-summary.csv`; báo token
  vào/ra, currency, cost trung bình/câu, latency trung bình/p95 và coverage từng cấu hình.
  Latency model và thời gian API đầu cuối là hai đại lượng riêng.
- [ ] Hai người thật chấm độc lập, lưu danh tính và hai bảng gốc, đối chiếu bằng chứng,
  đếm câu lệch và chốt trong adjudication theo rubric.
- [ ] Điền summary cuối, nhóm câu yếu nhất và khuyến nghị 1/2 dựa trên số đo; cập nhật
  mục “AI Assistant — chất lượng đo được” trong query-api README.
- [ ] Commit output runtime/bảng chấm thật sau khi kiểm tra không có secrets; chỉ khi
  acceptance criteria đầy đủ mới đổi PR sang ready và dùng `Closes #108`.

## Kiểm chứng offline đã chạy

Python 3.11.18, `cd query-api && python -m pytest -q -rs`: **386 passed, 7 skipped**.
Bảy test live storage bị skip vì chưa cấu hình `AUTH_TEST_OPENSEARCH_URL`; có một
Starlette/httpx deprecation warning từ dependency. Log đầy đủ ở
[validation/pytest-query-api.txt](validation/pytest-query-api.txt), metadata ở
[validation/summary.json](validation/summary.json).

CLI thực tế đã kiểm tra `--help` (exit 0), catalog chưa bind và mapping mẫu chưa điền
(đều exit 2, không tạo output); xem [cli-preflight.json](validation/cli-preflight.json).
Các kiểm tra binding thành công/sai fault/lỗi HTTP trong pytest dùng mock, không gọi
Azure/Langfuse. Đây là bằng chứng kiểm thử code, không thay thế checklist đo thật bên trên.

## Số liệu chưa được xác minh

- Cấu hình 1: điểm/60 **pending**; số câu 3/3 **pending**; lỗi API **pending**;
  token/cost/mean latency/p95 **pending**; hai người chấm/số câu lệch **pending**.
- Cấu hình 2: điểm/60 **pending**; số câu 3/3 **pending**; lỗi API **pending**;
  token/cost/mean latency/p95 **pending**; hai người chấm/số câu lệch **pending**.
- Khuyến nghị cuối và 2–3 dạng câu yếu nhất: **pending**. Giữ mặc định đang có (2)
  trong PR chuẩn bị này; đây không phải kết luận rằng 2 tốt hơn 1.

`scores-round*.csv` và `langfuse-summary.csv` chỉ được tạo khi đo thật. `questions.json`
hiện tại là catalog chưa bind; file chạy thật nằm ở `prepared/questions.json` và manifest
giữ hash của nó. Không coi template trống hoặc test mock là bằng chứng hoàn thành issue.
