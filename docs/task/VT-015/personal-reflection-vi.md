# Bản nháp phản ánh cá nhân về VT-015

Đây là bản nháp có hỗ trợ AI, để người học tự kiểm tra và điều chỉnh trước khi nộp.
Nội dung dưới đây chỉ dựa trên công việc và bằng chứng đã lưu trong repository;
không khẳng định việc thực hiện độc lập hoặc kết quả triển khai thực tế.

---

Qua VT-015, tôi nhận ra rằng kiểm thử chức năng cần gắn với rủi ro cụ thể. Bảng quyết định giúp phân biệt quyền đọc, quyền phê duyệt và yêu cầu giữ nguyên dữ liệu gốc. Kết quả RED có 14 ca thất bại và 8 ca thành công cho thấy phần thiếu trước khi triển khai GREEN.

Bài học quan trọng với tôi là không diễn giải kết quả rộng hơn phạm vi kiểm thử. Đột biến thay thao tác tạo nguyên tử bằng ghi đè đã bị phát hiện, nhưng nguyên nhân là hợp đồng của client giả. Điều đó chưa chứng minh khả năng xử lý tranh chấp của OpenSearch thật. Việc ghi rõ giới hạn này làm báo cáo đáng tin cậy hơn.

Kiểm tra thứ tự chạy cũng cho thấy một vấn đề mà bộ kiểm thử thông thường bỏ sót: fixture làm mất trạng thái dùng chung. Chuỗi tái hiện ngắn và lần chạy xáo trộn sau sửa cung cấp bằng chứng rõ hơn việc chỉ chạy lại toàn bộ rồi thấy màu xanh. Tôi hiểu thêm rằng lỗi có thể nằm trong cách kiểm thử, không nhất thiết ở mã sản phẩm.

Tôi cũng thấy giá trị của việc tách tỷ lệ bao phủ khỏi kết luận về chất lượng. Các nhánh phân quyền và lưu trữ cần được kiểm tra bằng đầu vào có ý nghĩa. Kết quả tải SQLite qua HTTP giúp đánh giá cục bộ, nhưng không thay thế kiểm thử hệ thống phân tán.

AI hỗ trợ lập kế hoạch, viết mã, kiểm thử và tổng hợp tài liệu trong quá trình này. Trách nhiệm của người nộp vẫn là đọc lại thay đổi, đối chiếu nhật ký và trình bày trung thực. Trước khi coi tính năng sẵn sàng triển khai, tôi cần thêm bằng chứng trên OpenSearch và rà soát cấu hình vận hành.
