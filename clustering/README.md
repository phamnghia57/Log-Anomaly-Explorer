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
- Output: ghi `ClusterRecord` theo [`cluster-record.schema.json`](../docs/architect/contracts/cluster-record.schema.json), Nghĩa đọc để phục vụ Incident View

## Evidence sở hữu

- **Labeled incidents**: `evaluation/labeled_incidents.json` — mỗi sự cố thật được gán nhãn thủ công, thường tạo ra từ fault injection của Mạnh
- **Precision/recall**: `evaluation/precision_recall.py` — đo trên labeled incidents ở trên

## Ch?y module

C?n OpenSearch c?a ingestion ho?t ??ng tr??c. Worker l? job n?n:

```powershell
cd clustering
pip install -r requirements.txt
python -B -m src.worker --once
python -B -m src.worker
```

D?ng `--window-to <ISO8601>` ?? x? l? m?t c?a s? c? th?.

C?u h?nh qua bi?n m?i tr??ng: `OPENSEARCH_URL` (http://localhost:9200),
`OPENSEARCH_USER`, `OPENSEARCH_PASSWORD`, `OPENSEARCH_VERIFY_CERTS` (false),
`LOG_INDEX` (logs), `CLUSTER_INDEX` (clusters), `WINDOW_SECONDS` (60),
`HISTORY_WINDOWS` (30), `INGESTION_LAG_SECONDS` (10), `ANOMALY_THRESHOLD` (2.0),
`ALERT_WEBHOOK_URL` v? `ALERT_COOLDOWN_SECONDS` (600).

Ch? nh?m ERROR/FATAL theo service v? message chu?n h?a. Baseline d?ng c?c c?a s?
tr??c ??, bao g?m c?a s? kh?ng c? l?i. C?n ?? d? li?u l?ch s? ?? tr?nh cold-start.
??u ra l?u ??ng ClusterRecord v?o index clusters, gi? log_ids v? trace_ids.
M?i c?m l?u c?a s? quan s?t m?i nh?t. Worker ch?y m?t instance, kh?ng t? ch?y b?
khi d?ng l?u; cooldown alert ch? l?u trong b? nh?.

## ??nh gi?

Gi? `evaluation/labeled_incidents.json` v? `evaluation/precision_recall.py`
theo y?u c?u ?? t?i. Truy?n file d? ?o?n c?a l?n ch?y c?n ??nh gi?:

```powershell
python -B evaluation/precision_recall.py --predictions <predictions.json>
```

Th?m `--alerted-only` ?? ch? ?o alert ?? g?i. M?c ??nh ?o c?c c?m anomalous v? alerted.
Gh?p m?t-m?t theo service/signature v? kho?ng th?i gian; d? ?o?n l?p t?nh l? false positive.
