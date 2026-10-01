# clustering — Nam

"Bộ não" phát hiện bất thường: nhóm lỗi tương tự, tính anomaly score, phát alert khi vượt ngưỡng.

## Trách nhiệm

- [ ] Hoàn thiện thuật toán nhóm lỗi trong `src/clustering.py` (hiện chỉ group theo message nguyên văn — cần chuẩn hoá/so khớp thực sự)
- [ ] Hoàn thiện cách tính baseline tần suất + anomaly score trong `src/anomaly_score.py`
- [ ] Cấu hình `ANOMALY_THRESHOLD` và `ALERT_WEBHOOK_URL` cho `src/alert.py`
- [ ] Phối hợp với Mạnh: dùng `/simulate-error` để tạo các giai đoạn bất thường có kiểm soát, rồi điền vào `evaluation/labeled_incidents.json`
- [ ] Chạy `evaluation/precision_recall.py` để có số liệu precision/recall thật, không chỉ chạy trên dữ liệu rỗng

## Hợp đồng đang tuân theo

- Input: đọc log đã lưu từ Ingestion (Minh)
- Output: ghi `ClusterRecord` theo [`cluster-record.schema.json`](../docs/contracts/cluster-record.schema.json), Nghĩa đọc để phục vụ Incident View

## Evidence sở hữu

- **Labeled incidents**: `evaluation/labeled_incidents.json` — mỗi sự cố thật được gán nhãn thủ công, thường tạo ra từ fault injection của Mạnh
- **Precision/recall**: `evaluation/precision_recall.py` — đo trên labeled incidents ở trên
