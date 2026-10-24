# clustering — Nam

"Bộ não" phát hiện bất thường: nhóm lỗi tương tự, tính anomaly score, phát alert khi vượt ngưỡng.

## Trách nhiệm

- [x] Hoàn thiện thuật toán nhóm lỗi trong `src/clustering.py` (chuẩn hoá giá trị động và hoa/thường)
- [x] Hoàn thiện cách tính baseline tần suất + anomaly score trong `src/anomaly_score.py`
- [ ] Cấu hình `ANOMALY_THRESHOLD` và `ALERT_WEBHOOK_URL` cho `src/alert.py`
- [ ] Phối hợp với Mạnh: dùng `/simulate-error` để tạo các giai đoạn bất thường có kiểm soát, rồi điền vào `evaluation/labeled_incidents.json`
- [x] Chạy `evaluation/precision_recall.py` trên dữ liệu fault injection mới (kết quả bên dưới)

## Hợp đồng đang tuân theo

- Input: đọc log đã lưu từ Ingestion (Minh)
- Output: ghi `ClusterRecord` theo [`cluster-record.schema.json`](../docs/architect/contracts/cluster-record.schema.json), Nghĩa đọc để phục vụ Incident View

## Evidence sở hữu

- **Labeled incidents**: `evaluation/labeled_incidents.json` — mỗi sự cố thật được gán nhãn thủ công, thường tạo ra từ fault injection của Mạnh
- **Precision/recall**: `evaluation/precision_recall.py` — đo trên labeled incidents ở trên

## Chạy module

Chạy từ thư mục gốc repository, cần OpenSearch của ingestion hoạt động trước:

```powershell
pip install -r clustering/requirements.txt
python -B -m clustering.src.worker --once
python -B -m clustering.src.worker
```

Dùng `--window-to <ISO8601>` để xử lý một cửa sổ cụ thể.

Cấu hình kết nối dùng chung qua `ingestion.src.storage.build_store()`:
`OPENSEARCH_URL` (http://localhost:9200), `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD`,
`OPENSEARCH_VERIFY_CERTS` (false), `OPENSEARCH_TIMEOUT` (10), `LOG_INDEX` (logs).
Worker yêu cầu `STORAGE_BACKEND=opensearch` (mặc định).
Cấu hình clustering: `CLUSTER_INDEX` (clusters), `WINDOW_SECONDS` (60),
`HISTORY_WINDOWS` (30), `INGESTION_LAG_SECONDS` (10), `ANOMALY_THRESHOLD` (2.0),
`ALERT_WEBHOOK_URL` và `ALERT_COOLDOWN_SECONDS` (600).

Chỉ nhóm ERROR/FATAL theo service và message chuẩn hoá. Baseline dùng các cửa sổ
trước đó, bao gồm cửa sổ không có lỗi. Cần đủ dữ liệu lịch sử để tránh cold-start.
Đầu ra lưu đúng ClusterRecord vào index clusters, giữ log_ids và trace_ids.
Mỗi cụm lưu cửa sổ quan sát mới nhất. Worker chạy một instance, không tự chạy bù
khi dừng lâu; cooldown alert chỉ lưu trong bộ nhớ.

Query API có thể dùng `OpenSearchStore.list_clusters(status=None, since=None,
limit=100, offset=0)` và `get_cluster(cluster_id)`. Danh sách sắp theo `last_seen`
giảm dần; `since` lọc `last_seen >= since`. ID không tồn tại trả về `None`.
Dùng `store.log_store.get_logs(record['log_ids'])` để lấy log cho Incident View.

## Đánh giá

### Đợt dữ liệu mới ngày 23/10/2026

Đã gọi demo-app từ source hiện tại tại commit
`462989449e0b0abf6d0c38ccb541ea2efa055f12`, qua ingestion vào OpenSearch,
rồi replay `pipeline.analyze` và chạy `evaluation/precision_recall.py`.
Đây là lần tạo dữ liệu mới, không dùng lại log hay predictions ngày 20/10.

| Phương án | Precision | Recall | TP | FP | FN |
|---|---:|---:|---:|---:|---:|
| Rule-only | 1,000 (100%) | 1,000 (100%) | 10 | 0 | 0 |
| Rule + ML | 1,000 (100%) | 1,000 (100%) | 10 | 0 | 0 |

Nguồn: index `pr-fresh-logs`, 90 ERROR được xác nhận lưu đủ so với 90 request
fault injection. Hai platform `web`/`mobile-api`, mỗi platform chạy năm fault
`value`, `connection`, `runtime`, `timeout`, `downstream`; HTTP status được kiểm
tra theo từng fault. Nhãn có 10 incident dựa trên tham số injection, cần nhóm
review; đây là log thật từ demo local, không phải dữ liệu production.

Cấu hình: cửa sổ 30 giây, hai cửa sổ baseline, threshold 2,0. Mỗi tổ hợp
service/fault có 1 lỗi/cửa sổ baseline, 6 lỗi trong burst, 1 lỗi khi phục hồi.
Đo trên cả cửa sổ burst và phục hồi; mỗi phương án có 20 ClusterRecord,
10 anomalous và 10 normal. Script chỉ tính anomalous/alerted mặc định;
không gửi webhook và không đo alert delivery. ML dùng state mới, giữ giữa hai
cửa sổ đánh giá, similarity 0,9, margin 0,05, max templates 2.000.
Runtime image local `log-clustering-benchmark:local` (Python 3.13.17,
scikit-learn 1.7.2), source hiện tại được mount vào container.

Bằng chứng: [runs/20261023T164049Z](evaluation/runs/20261023T164049Z/), gồm
`logs.json`, `requests.json`, `labels.json`, `config.json`, `ml-state.json`,
`predictions-rule.json`, `predictions-ml.json` và hai file `metrics-*.json`.
Thời gian trong file dùng UTC; run ID là thời điểm bắt đầu baseline.
Để tính lại metrics từ thư mục gốc, sau khi cài requirements:

```powershell
python -B -m clustering.evaluation.precision_recall --predictions clustering/evaluation/runs/20261023T164049Z/predictions-rule.json --labels clustering/evaluation/runs/20261023T164049Z/labels.json
python -B -m clustering.evaluation.precision_recall --predictions clustering/evaluation/runs/20261023T164049Z/predictions-ml.json --labels clustering/evaluation/runs/20261023T164049Z/labels.json
```

Harness tạo dữ liệu: `evaluation/fresh_run.py`, chạy trong mạng Docker có
`opensearch`, `pr-eval-ingestion:8000`, `pr-eval-demo:8001`; ingestion phải dùng
`LOG_INDEX=pr-fresh-logs`. Harness kiểm tra HTTP, giới hạn thời gian mỗi cửa sổ,
độ đầy đủ của log rồi xuất nhãn/predictions vào thư mục run mới.

Kết quả xác nhận phát hiện burst có kiểm soát; mẫu nhỏ, message cố định và chỉ
một cửa sổ phục hồi nên chưa đủ kết luận chất lượng production hoặc ML tốt hơn
rule-only. Không so trực tiếp với kết quả 92% của project/bộ dữ liệu khác.

Chạy từ thư mục gốc repository:

```powershell
python -B -m clustering.evaluation.precision_recall --predictions <predictions.json>
```

Thêm `--alerted-only` để chỉ đo alert đã gửi. Mặc định đo các cụm anomalous và alerted.
Ghép một-một theo service/signature và khoảng thời gian; dự đoán lặp tính là false positive.
Nhãn được chuẩn hoá theo cùng quy tắc với log đầu vào.
Thay đổi chuẩn hoá hoa/thường làm đổi ID các cụm cũ có chữ hoa; cần tạo lại dữ liệu
cụm và file predictions trước khi so sánh với lần chạy mới.

## ML augment

Worker đã tích hợp TF-IDF character n-gram + cosine để ghép thêm template gần
nhau trong cùng service. Rule-based vẫn chạy trước và là fallback khi thiếu thư
viện, lỗi state/inference hoặc vượt ngân sách template. Không dùng DL trong bước này.

```powershell
pip install -r clustering/requirements-ml.txt
$env:ML_AUGMENT_ENABLED = "true"
python -B -m clustering.src.worker --once
```

`ML_AUGMENT_ENABLED` mặc định `true`; đặt `false` để chạy hoàn toàn rule-based.
Nếu chỉ cài requirements cơ bản và thiếu scikit-learn, worker cảnh báo rồi dùng rule.
API `analyze()` chỉ augment khi được truyền `augmenter`.

Cấu hình: `ML_SIMILARITY_THRESHOLD=0.9`, `ML_SIMILARITY_MARGIN=0.05`,
`ML_MAX_TEMPLATES=2000`, `ML_STATE_PATH=clustering/data/ml_templates.json`.
Ngưỡng là giá trị khởi đầu, chưa hiệu chỉnh trên log thật. Mỗi service dùng tối đa
20.000 đặc trưng sparse, so từng template với các đại diện, không tạo ma trận
similarity toàn bộ log. Đã có [benchmark sơ bộ và so sánh rule-only](BENCHMARK.md)
trong container giới hạn 2 CPU/4 GiB; chưa nghiệm thu trên VM riêng.

File state lưu ánh xạ template sang signature đại diện để ID ổn định sau restart.
Chỉ một worker được ghi file này; giữ file trên volume bền vững và không commit
vì chứa template log. Cùng ánh xạ được áp dụng cho lịch sử và hiện tại trước khi
tính baseline. Khi đổi policy, dùng state mới và xây lại baseline; bật/tắt ML có
thể đổi cách gom cụm và ID. File state hỏng không bị ghi đè tự động.

ML chỉ ghép khi similarity vượt ngưỡng và cách ứng viên thứ hai đủ xa. Exception
type hoặc status/code mâu thuẫn trong message gốc sẽ chặn việc ghép thêm. Các nhóm
đã được rule gộp sẵn vẫn giữ nguyên; ML không tách lại nhóm đó. Template mới không
có message đại diện trong khoảng dữ liệu hiện tại sẽ giữ thành nhóm riêng.
