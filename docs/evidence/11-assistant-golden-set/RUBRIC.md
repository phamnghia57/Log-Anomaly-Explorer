# Rubric golden set AI Assistant — #108

Mỗi cấu hình có 20 câu × 3 tiêu chí = **60 điểm**. Chấm câu trả lời cuối cùng trong
`scores-round1.csv` / `scores-round2.csv`, so với `expected` trong đúng bộ câu hỏi đã bind,
snapshot và kết quả tool/trace thực tế của lượt hỏi. Không chấm kết quả test mock như câu
trả lời của model. Nguồn ground truth: `demo-app/src/main.py::_inject_fault` và mục 5 runbook.

## Ba tiêu chí nhị phân

- `layer_status`: 1 khi nhận đúng tầng lỗi và không nêu status sai. `value` là validate
  nghiệp vụ (fault demo trả 422), `connection` là không tới được downstream (502),
  timeout là downstream chậm/timeout (504), runtime là lỗi ứng dụng (500).
  `error_type=runtime` một mình không phân biệt được timeout với runtime thông thường.
  HTTP status phải đối chiếu trace/response thật nếu được trình bày như một quan sát.
  Log mẫu không có status thì nhận đúng tầng và nói chưa xác minh status vẫn được 1;
  không bắt model đoán mã HTTP hay đọc mã nguồn mà nó không có quyền truy cập.
- `evidence`: 1 khi câu trả lời trích ít nhất một **message thực** hoặc **trace_id thực**
  từ ngữ cảnh/tool, dùng nó đúng ý nghĩa và liên quan nhận định. Có thể trích nguyên một
  đoạn message đủ để nhận diện, không bắt buộc toàn bộ stack. Chỉ nói “theo log” không được
  điểm. `evidence_ref` trong bảng chấm chỉ rõ file snapshot/tool và log/trace đối chiếu.
- `no_fabrication`: 1 khi không khẳng định thêm dữ kiện/nguyên nhân không được dữ liệu
  hỗ trợ. DNS, database, deploy, commit, duration, span hay trường payload chưa quan sát
  không được trình bày như sự thật. Giả thuyết được ghi rõ là cần xác minh và đề xuất bước
  kiểm tra phù hợp không bị coi là bịa. Đề xuất rollback không đồng nghĩa xác nhận rollback
  sẽ sửa được lỗi. Câu trả lời rỗng, hoặc có `error` trong output runner, nhận 0/0/0;
  công bố riêng số lỗi API/reset để phân biệt chất lượng trả lời với tính sẵn sàng.

`expected` là hướng dẫn ngữ nghĩa, không bắt khớp từng chữ. Nếu câu trả lời nói rõ chưa có
đủ bằng chứng thì không phạt vì thiếu một chi tiết chỉ người chấm biết từ source demo.
Nếu có status/span thật trong tool, dùng bằng chứng đó làm nguồn quyết định.

## Nhóm bad_schema: kiểm tra giới hạn dữ liệu

`bad_schema` gửi payload sai enum vào ingestion; nó đi quarantine, không thành cluster.
Assistant hiện không có tool quarantine. Bốn câu thuộc nhóm này dùng ngữ cảnh runtime
thật, không chứa bằng chứng về bất kỳ sự kiện quarantine nào.

- `layer_status=1`: phân biệt sự cố ứng dụng đang thấy với validation tại ingestion, nói
  không đủ bằng chứng kết luận sự kiện sai schema/trường sai/status ingestion. Không đánh
  đồng HTTP 500 của runtime hoặc 502 từ demo với status của ingestion.
- `evidence=1`: dẫn message/trace runtime thực để giải thích dữ liệu đang có và giới hạn
  kết luận. Không yêu cầu dẫn bằng chứng quarantine không được cung cấp.
- `no_fabrication=1`: không bịa payload, `level=CRITICAL`, trace, số lượng quarantine hoặc
  khẳng định sự kiện có/không tồn tại. Đề nghị đọc quarantine/payload/response validation
  là bước tiếp theo hợp lệ. Chỉ vắng log không chứng minh chưa từng có payload sai schema.

Kết quả nhóm này đo khả năng thừa nhận thiếu dữ liệu; không được báo thành chất lượng điều
tra quarantine đầu cuối. Nên công bố điểm nhóm này riêng bên cạnh tổng 60.

## Hai người chấm và chốt bất đồng

1. Ghi hai danh tính thật và phân vai A/B trước khi chấm. Mỗi người dùng bốn nguồn giống
   nhau: câu hỏi/expected, câu trả lời thô, snapshot ban đầu và tool/trace của lượt đo.
2. Mỗi người điền ba tiêu chí, `rationale`, `evidence_ref`, `answer_ref` riêng, không xem
   bảng người kia. Ô trống là pending, không tự chuyển thành 0. Không dùng agent làm người
   chấm độc lập thay con người.
3. Sau khi cả hai hoàn thành, lưu nguyên hai bản. Một câu **lệch** khi bất kỳ một trong ba
   tiêu chí khác nhau. Đếm theo cặp `(tool_rounds, id)`: tối đa 20 câu lệch mỗi cấu hình,
   không đếm một câu thành ba chỉ vì khác cả ba tiêu chí.
4. Sao chép `adjudication.template.csv`, điền hai bộ điểm gốc, `disagreed` (0/1), ba điểm
   cuối và `reason` chốt sau thảo luận. Dòng chưa thống nhất giữ trống điểm cuối/pending;
   không công bố điểm cuối hoặc khuyến nghị khi còn dòng chưa chốt.
5. Tổng cuối = tổng 60 ô điểm mỗi cấu hình. `fully_correct_out_of_20` là số câu đạt 3/3.
   Báo số lỗi, số câu lệch, điểm theo nhóm và 2–3 dạng câu yếu nhất kèm ID ví dụ. Không loại
   câu lỗi khỏi mẫu số 60 để làm đẹp kết quả. Retry nếu cần phải giữ cả output cũ và lý do,
   ghi rõ lượt nào được dùng cho so sánh và chi phí các lần thử.

Hiện các bảng được commit là **template chưa chấm**. Chưa có hai người chấm hoặc kết quả
Azure/Langfuse, do đó chưa có điểm hay đề xuất giữ 1/2 được xác minh.
