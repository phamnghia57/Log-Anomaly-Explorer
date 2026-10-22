# clustering — Nam

"Bộ não" phát hiện bất thường: nhóm lỗi tương tự, tính anomaly score, phát alert khi vượt ngưỡng.

## Trách nhiệm

- [x] Hoàn thiện thuật toán nhóm lỗi trong `src/clustering.py` (chuẩn hoá giá trị động và hoa/thường)
- [x] Hoàn thiện cách tính baseline tần suất + anomaly score trong `src/anomaly_score.py`
- [ ] Cấu hình `ANOMALY_THRESHOLD` và `ALERT_WEBHOOK_URL` cho `src/alert.py`
- [ ] Phối hợp với Mạnh: dùng `/simulate-error` để tạo các giai đoạn bất thường có kiểm soát, rồi điền vào `evaluation/labeled_incidents.json`
- [ ] Chạy `evaluation/precision_recall.py` để có số liệu precision/recall thật, không chỉ chạy trên dữ liệu rỗng

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
