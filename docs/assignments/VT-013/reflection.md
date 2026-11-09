# VT-013 — Reflection

MSSV: **23001904**. Bản nháp do AI hỗ trợ, cần sinh viên đọc và xác nhận trước khi nộp. **328 từ**, tính bằng tách khoảng trắng trên sáu đoạn nội dung dưới đây, không tính tiêu đề hoặc ghi chú.

Niềm tin vào Undo tăng khi kiểm thử đối chiếu cả phản hồi API lẫn tài liệu OpenSearch đã lưu. Khôi phục chính xác lịch sử có Unicode, null và tool messages thuyết phục hơn việc chỉ nhìn nút Undo hoạt động. Kiểm thử khởi động lại API giúp phân biệt persistence thật với cache trình duyệt.

RED rồi GREEN cung cấp dấu vết rằng kiểm thử phát hiện hành vi còn thiếu trước khi sửa. T-11 đã đạt ngay từ RED nên không bị ép thất bại. Việc giữ kết quả đó giúp tránh nhầm mọi thay đổi là một cải tiến và giữ oracle độc lập với implementation.

Mutation M-01 cho thấy nuốt exception vẫn sai ngay cả khi CAS ngăn ghi đè. Bốn assertion phát hiện HTTP 409 thay vì 503. Kết quả này chứng minh khả năng nhận diện lỗi contract cụ thể, không chứng minh mọi lỗi storage đều được phát hiện. Khôi phục đúng hash bảo đảm mutant không lọt vào bài nộp.

Coverage cao không bảo đảm tính đúng: fake có thể mô phỏng sai server, nhánh lỗi chưa chạy vẫn nguy hiểm, còn cùng một dòng có nhiều kết quả. Vì vậy cần kết hợp ma trận rủi ro, real integration và lặp concurrency bằng barrier, đồng thời công khai những nhánh chưa được kiểm chứng.

NFR hiệu năng không đạt ở cả ba kích thước lịch sử; một ReadError còn chưa rõ nguyên nhân. Giữ NOT MET đáng tin hơn thay ngưỡng hoặc loại mẫu chậm. Quyết định giữ production tránh tối ưu theo phỏng đoán khi chưa xác định bottleneck.

Rủi ro còn lại là phản hồi bị mất sau commit, failover và cấu hình môi trường khác. Kiểm thử giá trị nhất tiếp theo là chủ động làm mất phản hồi Undo sau persistence, rồi xác minh GET reconciliation và không tự gửi lại mutation. Đó là đề xuất tương lai, chưa thực hiện trong bài này.
