# Kiểm tra tái lập precision/recall — issue #86

Ngày kiểm tra: 13/11/2026. Source base: `1878158`.

## Bộ nhãn công bố

`labeled_incidents.json` được đồng bộ nguyên nội dung từ
`runs/20261023T164049Z/labels.json`: 10 incident, hai service
`demo-web`/`demo-mobile-api`, năm fault `value`, `connection`, `runtime`,
`timeout`, `downstream`. Bộ mặc định cũ có sáu incident của ngày 20/10,
khác khoảng thời gian và không thể dùng để tái lập bảng kết quả ngày 23/10.
Nguồn nhãn vẫn là tham số fault injection; đang chờ nhóm review.

## Lệnh tái lập

Chạy từ thư mục gốc repo, không cần Docker, OpenSearch hoặc scikit-learn
vì dùng predictions đã lưu:

```powershell
python -B -m clustering.evaluation.precision_recall --predictions clustering/evaluation/runs/20261023T164049Z/predictions-rule.json
python -B -m clustering.evaluation.precision_recall --predictions clustering/evaluation/runs/20261023T164049Z/predictions-ml.json
```

| Predictions | Precision | Recall | TP | FP | FN |
|---|---:|---:|---:|---:|---:|
| Rule-only | 1.0 | 1.0 | 10 | 0 | 0 |
| Rule + ML | 1.0 | 1.0 | 10 | 0 | 0 |

Hai lệnh đã chạy thành công với file nhãn mặc định. Kết quả khớp các file
`metrics-rule.json` và `metrics-ml.json` trong run gốc.

## Phạm vi và traffic bình thường

Mỗi file predictions có 20 record: 10 anomalous ở cửa sổ burst và 10 normal
ở cửa sổ phục hồi. Evaluator xét mọi record anomalous/alerted, nên nếu cửa sổ
phục hồi có cảnh báo không ghép được incident thì cảnh báo đó sẽ tăng FP.
Các record normal không được tính vào mẫu số precision; không có phép đo
true negative hoặc false positive rate trong kết quả này.

Đây là tính lại phép đo trên dữ liệu ngày 23/10, không thu log mới và không
chạy lại pipeline/ML. Precision 1.0 chỉ có nghĩa không có FP trong mẫu nhỏ này;
không chứng minh precision production hoặc ML tốt hơn rule-only.
Để đánh giá rộng hơn, cần thu thêm nhiều cửa sổ traffic bình thường độc lập,
bao gồm ERROR nền biến động, cùng incident được xác nhận độc lập để đo recall.
