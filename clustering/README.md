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

---

## Tri?n khai b? sung

# clustering — Nam

Module nhóm lỗi, tính anomaly score theo baseline lịch sử và gửi webhook. Chỉ dùng Python và httpx; không sửa hợp đồng chung.

## Chạy

Python 3.10+:

```powershell
cd clustering
pip install -r requirements.txt
python -B -m unittest discover -s tests -v
python -B evaluation/synthetic_demo.py
python -B evaluation/precision_recall.py --predictions evaluation/synthetic_predictions.json --labels evaluation/synthetic_incidents.json
python -B -m src.worker --once
python -B -m src.worker
```

OpenSearch của ingestion phải chạy trước. Worker là job nền, không cần uvicorn. Có thể chạy lại một cửa sổ cụ thể:

```powershell
python -B -m src.worker --window-to 2026-10-01T09:03:00Z
```

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| OPENSEARCH_URL | http://localhost:9200 | Cùng storage với ingestion |
| OPENSEARCH_USER / OPENSEARCH_PASSWORD | rỗng | Basic auth |
| OPENSEARCH_VERIFY_CERTS | false | Đặt true nếu dùng chứng chỉ hợp lệ |
| LOG_INDEX | logs | Index đầu vào, lấy log_id từ _id |
| CLUSTER_INDEX | clusters | Index đầu ra cho query-api |
| WINDOW_SECONDS | 60 | Độ dài cửa sổ |
| HISTORY_WINDOWS | 30 | Số cửa sổ baseline trước cửa sổ hiện tại |
| INGESTION_LAG_SECONDS | 10 | Chờ ingestion trước khi đóng cửa sổ |
| ANOMALY_THRESHOLD | 2.0 | Bất thường khi score > ngưỡng |
| ALERT_WEBHOOK_URL | rỗng | Không cấu hình thì giữ anomalous |
| ALERT_COOLDOWN_SECONDS | 600 | Thời gian chặn alert lặp theo cluster_id |

## Thuật toán và đầu ra

- Chỉ nhóm ERROR/FATAL. Chuẩn hóa UUID, email, IPv4, hex, số và khoảng trắng; tách nhóm theo service. Đây là template clustering, chưa dùng semantic similarity/stack trace. Việc chuẩn hóa số có thể gom chung mã HTTP khác nhau; cần rà soát signature khi gán nhãn.
- ID ổn định theo service + signature. Không thay quy tắc chuẩn hóa khi đang đo một tập dữ liệu.
- Cửa sổ là [start, end). Baseline gồm các cửa sổ bằng nhau trước start, bao gồm cửa sổ có 0 lỗi; không dùng dữ liệu tương lai. Score = max(0, (count - mean) / max(std, sqrt(mean), 1)).
- Cần đủ lịch sử trong storage trước khi chạy: dữ liệu chưa thu thập cũng bị xem là 0 và có thể gây cold-start alert. Worker đọc toàn bộ khoảng bằng scroll, không cắt ở 1000 log.
- Index clusters chứa đúng ClusterRecord, không thêm service ngoài schema. _id = cluster_id. Mỗi cụm lưu cửa sổ quan sát mới nhất, gồm log_ids, trace_ids và thời điểm thực của log. Cụm không xuất hiện ở cửa sổ mới vẫn giữ bản ghi cũ; query-api nên lọc last_seen theo thời gian cần xem.
- Query-api có thể đọc index clusters, dùng log_ids để truy lại index logs và request_id gốc. Query-api hiện còn mock; phần nối dữ liệu thuộc module của Nghĩa.
- Webhook nhận cluster_id, score, service, first_seen. Chỉ đánh dấu alerted sau HTTP thành công; thất bại giữ anomalous để thử lại. Cooldown chỉ trong bộ nhớ, khởi động lại có thể gửi lại. Gửi webhook và ghi storage không phải giao dịch nguyên tử.
- Worker cần chạy một instance. Mỗi vòng xử lý cửa sổ hoàn tất gần nhất; không tự backfill khi dừng lâu, không tự bắt log đến trễ quá thời gian lag. Dùng --window-to để chạy bù theo từng cửa sổ tăng dần; chạy cửa sổ cũ sẽ ghi đè bản ghi mới của cùng cụm.

## Evaluation và evidence

`labeled_incidents.json` dành cho sự cố thực đã xác nhận, hiện để rỗng vì chưa có dữ liệu fault injection thật. Mỗi incident cần incident_id duy nhất, window_from/window_to có timezone, service, description và expected_cluster_signature đã chuẩn hóa.

`synthetic_demo.py` dựng baseline 2 lỗi/phút, sau đó tăng lên 8 lỗi/phút, thêm một nhóm bình thường và xuất `synthetic_predictions.json`. Nhãn nằm ở `synthetic_incidents.json`, ghi rõ dữ liệu tổng hợp; không phải bằng chứng fault injection thật.

Evaluator nhận JSON array ClusterRecord. Mặc định đo phát hiện (anomalous + alerted); thêm `--alerted-only` để đo alert đã gửi. Ghép theo cluster_id tính từ service/signature và giao nhau thời gian, mỗi prediction chỉ ghép một incident và ngược lại bằng maximum matching. Prediction lặp là false positive. Precision = TP/(TP+FP), recall = TP/(TP+FN); mẫu số 0 trả 0.0, không phải kết luận về chất lượng mô hình. Muốn đánh giá nhiều cửa sổ cần thu prediction của từng cửa sổ, vì index clusters chỉ giữ bản ghi mới nhất.

## Checklist

- [x] Template clustering, stable ID và liên kết log/trace
- [x] Baseline lịch sử, anomaly score và job OpenSearch
- [x] Alert có threshold, HTTP error handling, cooldown
- [x] Evaluator thời gian/service/signature, demo tổng hợp và unit tests
- [ ] Phối hợp Mạnh chạy /simulate-error và ghi nhãn thật
- [ ] Chạy OpenSearch + webhook thật, thu prediction và báo precision/recall thực tế

## Kiểm thử tích hợp ba module

Từ thư mục gốc repository, sau khi Docker Engine hoạt động:

```powershell
docker compose -f ingestion/docker-compose.yml up -d
python -B clustering/evaluation/run_integration.py
```

Script dùng cổng 18000 (ingestion), 18001 (demo-app), 18003 (webhook local), index riêng theo run_id. Script tự chạy và dừng các service Python do nó tạo, giữ index evidence. Không sửa module ingestion/demo-app.

Bài chạy gồm hai cửa sổ baseline, một spike và một recovery, mỗi cửa sổ 30 giây. Kiểm tra ba fault value/connection/runtime trên web/mobile, schema cụm, log/trace IDs và webhook HTTP thực. Evidence chỉ được xác nhận khi script kết thúc thành công và có report.json trong evaluation/integration/<run_id>/. Nhãn sinh tự động từ kịch bản injection cần người phụ trách xem lại trước khi đưa vào labeled_incidents.json chính.

Dependency instrumentation của demo-app hiện chỉ phát hành beta; nếu pip không tìm thấy opentelemetry-instrumentation-fastapi, cài riêng package đó bằng `pip install --pre opentelemetry-instrumentation-fastapi` trước khi cài requirements.

Lần thử ngày 2026-10-20 chưa hoàn tất: tải image OpenSearch lỗi unexpected EOF, sau đó Docker Desktop Linux Engine không phản hồi (500/EOF). Xem evaluation/integration-status.md. Chưa có số liệu precision/recall tích hợp thực tế.
