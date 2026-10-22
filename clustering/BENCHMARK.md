# Benchmark clustering — 22/10/2026

## Kết luận hiện tại

TF-IDF + cosine có thể dùng làm augment nhẹ cho workload đã đo: tối đa 1.800
template/36.000 log trong khoảng dữ liệu lịch sử + hiện tại, một worker, không
gọi dịch vụ ML bên ngoài. Rule-only nhanh hơn và tốn ít RAM hơn; ML có ích khi
template khác câu chữ nhưng tương tự về từ vựng. Giữ rule-based làm fallback.

Đây là kết quả **container giới hạn 2 CPU/4 GiB trên Docker Desktop**, chưa phải
nghiệm thu trên VM riêng 2 vCPU/4 GB. Chưa có quyền truy cập VM đó. Không khẳng
định toàn bộ OpenSearch + ingestion + clustering đủ 4 GB dựa trên phép đo riêng
clustering. Chưa benchmark MiniLM hoặc model DL, nên không có cơ sở so tốc độ/
chất lượng với các model đó.

## Môi trường và phương pháp

- Linux WSL2; Python 3.13.17; scikit-learn 1.7.2, NumPy 2.5.4, SciPy 1.18.1.
- Docker Engine có 4 CPU và 4.050.214.912 byte RAM. Container bị giới hạn quota
  `cpu.max=200000 100000` (2 CPU), `memory.max=4294967296`, không có swap.
  RAM vật lý dùng chung thấp hơn giới hạn container; đây không phải máy có 4 GiB
  dành riêng cho benchmark.
- Một process worker, BLAS/OMP một thread. CPU đo bằng process CPU time / wall
  time; 100% tương đương khoảng một lõi, không phải dùng hết cả hai CPU.
- Đo `pipeline.analyze`, gồm chuẩn hoá, nhóm, augment, state JSON và tính score.
  Không gồm đọc/ghi OpenSearch, gửi webhook hoặc thời gian khởi động interpreter.
  Lần cold có tính import ML và fit vectorizer trong lần gọi đầu.
- Workload tổng hợp: một service, template khác nhau với code riêng để ngăn gộp
  không đúng; mỗi template có log ở cả baseline và cửa sổ hiện tại. Không đại diện
  cho mọi phân bố log, số service hoặc độ dài stack trace trong vận hành.
- Mỗi ca chạy process riêng: một cold, năm warm đã có ánh xạ, một ca thêm 10%
  template. Cột warm max là giá trị lớn nhất trong năm lần; không gọi đó là p95
  vận hành. RSS lấy mẫu 5 ms và đọc ở cuối lần gọi, có thể bỏ lỡ đỉnh rất ngắn.
- OpenSearch vẫn chạy ngoài container, chia sẻ Docker VM; không có CPU pinning,
  do đó kết quả có ảnh hưởng tải nền và không phải capacity test dài hạn.

## CPU/RAM và thời gian

| Template / tổng log | Phương án | Cold (s) | Warm max, 5 lần (s) | Thêm 10% template (s) | Peak RSS trong ca (MiB) |
|---|---|---:|---:|---:|---:|
| 50 / 1.000 | Rule-only | 0,023 | 0,036 | 0,020 | 23,5 |
| 50 / 1.000 | ML augment | 2,014 | 0,034 | 0,034 | 107,1 |
| 150 / 3.000 | Rule-only | 0,065 | 0,089 | 0,060 | 25,1 |
| 150 / 3.000 | ML augment | 2,181 | 0,268 | 0,102 | 109,2 |
| 300 / 6.000 | Rule-only | 0,146 | 0,155 | 0,139 | 27,3 |
| 300 / 6.000 | ML augment | 3,320 | 0,225 | 0,205 | 111,8 |
| 1.000 / 10.000 | Rule-only | 0,290 | 0,303 | 0,378 | 31,0 |
| 1.000 / 10.000 | ML augment | 3,661 | 0,419 | 1,195 | 117,8 |
| 1.800 / 36.000 | Rule-only | 0,953 | 1,751 | 1,045 | 49,3 |
| 1.800 / 36.000 | ML augment | 4,173 | 2,219 | 1,750 | 137,4 |

Ở ca ML lớn nhất, CPU/wall khoảng 100–101% của một lõi. Không ghi nhận timeout,
fallback hoặc OOM trong lần đo cuối. Các thời gian nằm dưới cửa sổ mặc định 60
giây cho workload này; chưa cộng I/O hoặc đảm bảo SLO cho mọi workload. Bộ nhớ
của toàn VM chưa được benchmark.

Benchmark ban đầu phát hiện phần guard ghép cụm quét lại toàn bộ log cho từng
cặp template. Code đã được tối ưu bằng cache guard theo template/canonical trong
một lần xử lý. So sánh bản trước/sau trên 60 cửa sổ replay có ánh xạ lưu giữa các
lần: kết quả mapping giống nhau. Các số ở bảng trên đo code sau tối ưu.

## Chất lượng so với rule-only

Metric dưới đây là **pairwise clustering precision/recall/F1**, không phải metric
phát hiện incident. Hai log cùng nhãn/service phải thuộc cùng cụm. Mọi cặp log
trong tập được đối chiếu, không chỉ chọn cặp dự đoán đúng.

### 42 log thật từ fault injection có kiểm soát

Replay log đã lưu trong OpenSearch từ demo-app, gồm ba loại lỗi trên web/mobile.
Nhãn lấy từ loại fault đã biết, không phải log production được gán nhãn độc lập.

| Phương án | Precision | Recall | F1 |
|---|---:|---:|---:|
| Rule-only | 1,000 | 1,000 | 1,000 |
| ML mặc định 0,9 / margin 0,05 | 1,000 | 1,000 | 1,000 |

Template trong tập này cố định; kết quả chỉ xác nhận augment không làm sai các
nhóm đó, **không chứng minh ML tốt hơn rule-only trên log vận hành**.

### Bộ semantic tự soạn, tách validation và holdout

Mỗi tập có 48 log, tám nhóm lỗi, ba biến thể câu chữ và hai request ID mỗi biến
thể. Hai tập dùng nhóm lỗi khác nhau nhưng có cấu trúc câu tương tự. Đây là tập
synthetic nhỏ, không được coi là đánh giá độc lập đại diện cho vận hành.

| Phương án trên holdout | Precision | Recall | F1 | TP / FP / FN |
|---|---:|---:|---:|---|
| Rule-only | 0,667 | 0,200 | 0,308 | 24 / 12 / 96 |
| ML mặc định 0,9 / margin 0,05 | 0,857 | 0,600 | 0,706 | 72 / 12 / 48 |
| ML ứng viên 0,8 / margin 0,1 | 0,880 | 0,733 | 0,800 | 88 / 12 / 32 |

Quét threshold 0,65–0,95 và margin 0 / 0,05 / 0,1 trên validation; chỉ dùng
holdout sau khi chọn ứng viên. Không cấu hình nào đạt mục tiêu precision >=95%
trên validation. Vì vậy 0,8 / 0,1 chỉ là ứng viên F1 cao nhất trong lần thử,
**không phải cấu hình đã đạt yêu cầu để triển khai**. Giữ nguyên mặc định 0,9 / 0,05.

Cả ba phương án đều có 12 cặp gộp nhầm do rule hiện tại thay số HTTP status bằng
`<NUM>` trước khi nhóm. ML không thêm FP trên bộ này, nhưng không thể tách lại
nhóm rule đã gộp. Cần đánh giá riêng việc giữ error/status code khi chuẩn hoá và
gán nhãn thêm log thực tế trước khi kết luận precision vận hành.

## Bằng chứng và tái lập

Raw data và harness nằm trong `data/` đã gitignore, không đưa log lên Git:

- `data/benchmark-optimized/environment.json`: version, quota và SHA-256 source.
- `data/benchmark-optimized/performance.json`: từng cold/warm/churn, CPU và RSS.
- `data/benchmark-optimized/quality.json`: toàn bộ grid và kết quả quality.
- `data/benchmark-optimized/curated_validation.json`, `curated_holdout.json`: corpus tự soạn.
- `data/benchmark-optimized/memory_events.txt`: bộ đếm OOM của container.
- `data/run_benchmark.py`, `data/benchmark.Dockerfile`: harness và image.
- `data/benchmark_real_logs.json`: 42 log fault injection đã export từ OpenSearch.

Để chạy đúng trên VM riêng cần repository, các file benchmark/data ở trên và
quyền chạy Docker; các file gitignore không tự đi theo khi clone. Với Linux VM:

```sh
mkdir -p clustering/data/benchmark-vm
docker build -f clustering/data/benchmark.Dockerfile -t log-clustering-benchmark:local .
docker run --rm --name log-clustering-benchmark --cpus=2 --memory=4g --memory-swap=4g \
  --mount "type=bind,source=$PWD,target=/workspace,readonly" \
  --mount "type=bind,source=$PWD/clustering/data/benchmark-vm,target=/results" \
  log-clustering-benchmark:local python -B clustering/data/run_benchmark.py
```

Trước nghiệm thu, ghi cấu hình VM 2 vCPU/4 GB và đo tổng CPU/RAM của các dịch vụ
chạy chung. Cần thêm log có nhãn từ vận hành và chạy dài hơn để đo p95/throughput
ổn định. Chưa có địa chỉ truy cập VM nên các bước đó đang chờ thông tin từ người dùng.
