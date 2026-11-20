# #108 — Chấm tham khảo của Codex (AI)

**Đây là điểm AI tham khảo, chưa phải điểm của hai người chấm hoặc kết quả adjudication.**
Người đánh giá: `Codex`, loại `AI`, ngày 2026-11-20. Codex đã đọc nhận xét sơ bộ của Nghĩa
trước khi chấm nên bản này không được coi là đánh giá mù hoặc bằng chứng hai người độc lập.
Hai người thật nên nộp bảng riêng trước khi xem bản AI này để hạn chế ảnh hưởng.

## Nguồn và cách chấm

Nguồn cố định: commit `11704339da47cd5ac9be959c888c520603667182`, bản deploy lúc đo
`38defc3`, cùng 20 câu đã bind trong [prepared/questions.json](../prepared/questions.json).
Đọc thủ công cả 40 câu trả lời cuối trong hai file `scores-round*.csv`, đối chiếu expected,
[rubric gốc](../RUBRIC.md) và 5 log mẫu mỗi cluster. Script chỉ kiểm tra dữ liệu, dẫn chứng,
CSV và tính tổng; không tự quyết định điểm ngữ nghĩa bằng keyword.

- [round1.csv](round1.csv), [round2.csv](round2.csv): 20 câu/file, ba tiêu chí 0/1,
  tổng, lý do, trích dẫn thực tế và cờ cần người xem lại. `answer_ref` dùng đường dẫn +
  `#id=<question_id>` để tìm bản ghi CSV theo ID; đây không phải số dòng vật lý của CSV
  có câu trả lời nhiều dòng. `evidence_ref` dùng JSON pointer tới log mẫu.
- [validation.json](validation.json): hash nguồn, kiểm tra năm file trong manifest,
  tổng điểm theo tiêu chí/nhóm, câu rỗng và phép tính lại Langfuse bằng Decimal.
  Hash nguồn dùng Git blob, tránh khác biệt LF/CRLF của working copy Windows. Hash CSV
  mới cũng tương ứng nội dung LF trong Git blob.

Quy tắc áp dụng nhất quán:

- Chấp nhận dẫn message thật hoặc trace ID thật; không bắt buộc đọc thành công span để
  đạt điểm bằng chứng. `trace not found` không tự động mất điểm, cũng không tự động được 1.
- Thiếu status thì nói chưa xác minh vẫn được điểm tầng lỗi khi nhận đúng lỗi. Mã status
  trong **ví dụ logging/đề xuất** không được diễn giải thành mã đã quan sát.
- Xét năng lực theo tool được cấp trong lượt hỏi. Code deploy `38defc3` bỏ `tools` ở vòng
  cuối, nên rounds=1 không có tool. Không tự trừ điểm cho hai câu nói hiện không truy cập
  được tracing; cách nói về “quyền” vẫn được gắn cờ vì dễ hiểu thành giới hạn toàn hệ thống.
- Lỗi gọi API hoặc câu trả lời rỗng nhận 0/0/0 theo rubric; giữ mẫu số 60.
- Cờ `needs_human_review=1` đánh dấu chỗ diễn đạt/tranh luận hoặc dữ liệu cần xác nhận.
  Cờ 0 không thay thế việc hai người chấm độc lập. Điểm ở mọi dòng vẫn chỉ là đề xuất AI.

## Kết quả AI tham khảo

- **Rounds=1: 55/60 (91,67%), 17/20 câu đạt 3/3.** Tổng ba tiêu chí lần lượt
  tầng lỗi 19/20, bằng chứng 19/20, không bịa 17/20.
- **Rounds=2: 56/60 (93,33%), 18/20 câu đạt 3/3.** Tổng ba tiêu chí lần lượt
  19/20, 19/20 và 18/20.
- Điểm nhóm, rounds=1 → rounds=2: value 12/12 → 12/12; connection 9/12 → 9/12;
  timeout 11/12 → 11/12; runtime 11/12 → 12/12; bad_schema 12/12 → 12/12.
- Cả hai lượt có 20 bản ghi, 0 lỗi API, coverage 20/20, nhưng chỉ **19/20 câu có nội dung**.
  Điểm/60 chính thức và số câu lệch giữa hai người vẫn **pending**.

Ba tình huống yếu cần người chấm đối chiếu:

1. **Câu phản biện DNS không có nội dung:** `connection-502-04` rỗng ở cả hai lượt,
   `error` trống; 0/0/0 ở cả hai. Git blob gốc xác nhận đây không phải lỗi đọc CSV trên
   Windows. Telemetry ghi 1.200 output token ở cả hai lần, bằng cap cấu hình; có thể liên
   quan ngân sách sinh câu trả lời, nhưng không lưu `finish_reason` nên **chưa xác nhận
   nguyên nhân**. Không được coi “0 lỗi API” là “20 câu trả lời sử dụng được”.
2. **Nhầm metadata với lớp exception:** `timeout-504-01` ở cả hai lượt nhận đúng timeout
   và dẫn log thật, nhưng gán `error_type` cho timeout/`TimeoutError`. Snapshot ghi
   `metadata.error_type=runtime`, còn `TimeoutError` là exception trong stack. Bản AI cho
   1/1/0; người chấm cần xem liệu cách gọi chung “loại lỗi” có đủ để thay đổi tiêu chí 3.
   Không trừ lặp lại điểm tầng lỗi vì nhận đúng tình huống timeout.
3. **Suy ra span từ stack frame:** `runtime-500-03`, rounds=1, kết luận “có thể xác định
   span lỗi là đoạn mã _inject_fault” và nói span sẽ đánh dấu lỗi, trong khi chưa có trace.
   Stack chỉ chứng minh vị trí exception, không chứng minh tên/cấu trúc/status span:
   bản AI cho 1/1/0. Rounds=2 nói rõ chưa xác nhận span, dùng từ “khả năng” cho suy luận,
   nên được 1/1/1 dù trace không tìm thấy.

Góp ý kỹ thuật ngoài ba tiêu chí: `timeout-504-03` rounds=2 đề xuất “giảm sampling TTL”,
cần phân biệt sampling với retention TTL. Ghi cờ để sửa diễn đạt; không tự thêm tiêu chí
chấm chất lượng đề xuất sau khi đã đo. Nhóm bad_schema không bịa sự kiện/field/trace
quarantine, đạt 12/12 ở cả hai theo mục đích kiểm tra giới hạn dữ liệu.

## Đọc cùng chi phí và khả năng dùng tool

Tính lại từ [langfuse-per-question.csv](../langfuse-per-question.csv), đã khớp summary:
rounds=1 tốn **0,0017177625 USD/câu**, p95 model **10,075 s**; rounds=2 tốn
**0,00197874 USD/câu**, p95 **10,492 s**. Chênh **+0,0002609775 USD/câu (~15,2%)** và
**+0,417 s (~4,1%)**. P95 dùng nearest rank, không trộn với thời gian API đầu cuối.
Chi phí vẫn tính cả câu rỗng; số generation là 20 và 24, bốn câu có thêm generation là
các câu `-03` của bốn nhóm fault.

**Đề xuất AI: tạm giữ MAX_TOOL_ROUNDS=2**, phù hợp khuyến nghị vận hành của Nghĩa.
Một điểm hơn trong bộ chính là nhận định về span thận trọng hơn, không phải đã đọc được
trace: cả bốn lần get_trace ở lượt chính trả not found theo ghi chú đo và câu trả lời.
[Phép đo bổ sung](../tool-rounds-fair.json) trên một cụm khác có trace sống cho thấy
rounds=2 có get_trace và trả HTTP 500 đúng 2/2 lần; rounds=1 không lấy được status 0/2.
Payload tool trong file bổ sung bị cắt ngắn, nhưng phần lưu lại có `http_status: 500`
của span đầu; không coi nó là bản lưu đầy đủ mọi span.

Đây là một lượt/20 câu mỗi cấu hình và một câu bổ sung lặp hai lần, chưa đủ kết luận
chênh lệch chất lượng hoặc latency ổn định. Rubric cho phép thừa nhận thiếu dữ liệu nên
điểm cao không đồng nghĩa hoàn thành điều tra trace. Lý do không thấy trace không thể
suy riêng từ tuổi cluster: 14/11 đến 20/11 chưa đủ 7 ngày; Nghĩa ghi nhận Badger volume
mới. Chỉ dựa vào tuổi cluster cũng không xác định được tuổi của mọi span.

## Việc còn lại để đóng #108

Hai người thật chấm độc lập trên dữ liệu gốc, ghi danh tính, giữ hai bảng riêng rồi
đối chiếu/chốt adjudication. Sau đó mới điền hai ô điểm chính thức và số câu lệch trong
query-api README, chốt khuyến nghị cuối và đóng issue. Các template human và dữ liệu đo
gốc được giữ nguyên; bản tham khảo này không tạo số câu lệch giả hay thay điểm người thật.
