# Runbook — Log Anomaly Explorer

> Sở hữu: Nghĩa (nhóm trưởng). Viết từ kinh nghiệm vận hành thật trên bản deploy (Docker Compose
> + gateway Caddy + Vercel) — không phải quy trình lý thuyết.

## Khi nhận được Alert

1. **Nhận alert** (webhook) — nội dung gồm `cluster_id`, `score`, `service`, `first_seen`
   (xem payload chuẩn trong `docs/architect/contracts/api-contract.md` mục "Alert").
2. **Mở Incident View**: `GET /clusters/{cluster_id}` (hoặc trang `/clusters/:id` trên UI) để xem
   signature, score, danh sách log liên quan.
3. **Lần theo trace/request**: bấm icon ↗ cạnh một `trace_id` bất kỳ trong Incident View để mở
   trace thật trên Jaeger (`/jaeger/trace/{trace_id}`) — xem span nào trong request thực sự chậm
   hoặc lỗi, không chỉ đoán qua message.
   - **Lưu ý**: Jaeger chỉ có span cho trace sinh ra **sau khi** `demo-app` đã cấu hình đúng
     `OTEL_EXPORTER_OTLP_ENDPOINT`. Trace cũ hơn thời điểm đó sẽ báo "trace not found" vĩnh viễn —
     đây không phải lỗi, không cần debug thêm, chỉ cần dùng trace mới.
4. **Xác định phạm vi ảnh hưởng**: service nào (`demo-web` hay `demo-mobile-api`), từ khi nào
   (`first_seen` → `last_seen`), bao nhiêu log liên quan (`log_ids`).
5. **Hành động theo đúng loại lỗi** — `demo-app` ghi `metadata.error_type` trong mỗi log, chỉ có
   3 giá trị (xem `demo-app/src/main.py::_inject_fault`); lưu ý `fault=timeout` và
   `fault=downstream` đều ghi `error_type="runtime"`, phải nhìn **thêm HTTP status** hoặc
   `message` mới tách được:
   | `metadata.error_type` | HTTP status | Tầng lỗi | Hành động tương ứng (demo) |
   |---|---|---|---|
   | `value` | 422 | Nghiệp vụ — dữ liệu đầu vào không hợp lệ | Kiểm tra validate phía client/API, không phải lỗi hạ tầng |
   | `connection` | 502 | Hạ tầng — downstream dependency không tới được | Kiểm tra service downstream, DNS, network policy |
   | `runtime` (`message`: "Simulated downstream timeout") | 504 | Downstream chậm | Kiểm tra tải downstream, cân nhắc tăng timeout hoặc circuit breaker |
   | `runtime` (`message`: "Simulated runtime/downstream failure") | 500 | Tầng ứng dụng | Xem stack trace trong Incident View, có thể cần rollback bản deploy gần nhất |

   Nếu cùng 1 cụm có **nhiều service** (`demo-web` *và* `demo-mobile-api`) bị cùng 1 lỗi — đây là
   2 `ClusterRecord` riêng biệt (nhóm theo `(service, signature)`, không gộp chung), kiểm tra lần
   lượt từng cái qua `GET /clusters` lọc `status=alerted`.
6. **Đóng sự cố**: cập nhật trạng thái, ghi lại nguyên nhân gốc (root cause) — đây chính là dữ liệu
   cho `clustering/evaluation/labeled_incidents.json` (Nam dùng để đo precision/recall), nên ghi
   kèm đúng `window_from`/`window_to`/`service`/`expected_cluster_signature` ngay lúc còn nhớ rõ.

## Khi hệ thống báo động giả (false positive) nhiều

Alert có **cooldown 10 phút/cụm** (`ALERT_COOLDOWN_SECONDS`, mặc định `600`, xem
`clustering/src/alert.py`) — một cụm đã alert sẽ không gửi lại ngay trong cửa sổ đó dù vẫn vượt
ngưỡng, nên báo động giả dồn dập liên tục thường không phải do thiếu cooldown.

Các nguyên nhân thường gặp hơn và cách xử lý:

1. **Ngưỡng `ANOMALY_THRESHOLD` (mặc định `2.0`) quá nhạy** — tăng giá trị này trong `.env`
   (`ANOMALY_THRESHOLD=3.0` chẳng hạn), áp dụng cho `clustering` service, cần
   `docker compose up -d --force-recreate clustering` để nhận cấu hình mới (xem mục "Khi sửa
   cấu hình mà không thấy hiệu lực" bên dưới).
2. **Baseline tự thích nghi "quên" mất burst cũ** — hệ thống tính baseline từ
   `HISTORY_WINDOWS` (mặc định `30`) cửa sổ `WINDOW_SECONDS` (mặc định `60`) gần nhất. Nếu lặp
   lại đúng một kiểu lỗi nhiều lần trong thời gian ngắn (vd. test thủ công liên tục), baseline sẽ
   "học" luôn tần suất đó là bình thường, khiến burst **thật** sau đó bị đánh giá thấp hơn thực
   tế — không phải bug, mà là đặc tính của baseline thống kê theo lịch sử. Tránh lặp lại y hệt
   một burst nhiều lần liên tiếp khi test, hoặc đợi `HISTORY_WINDOWS × WINDOW_SECONDS` (~30 phút
   mặc định) để baseline "nguội" lại.
3. **Lớp TF-IDF augment (`ML_AUGMENT_ENABLED`, mặc định `true`) gộp nhầm 2 cụm khác nhau thành
   một** — kiểm tra bằng cách so `signature` hiển thị trên UI với `message` log gốc; nếu gộp sai,
   tăng `ML_SIMILARITY_THRESHOLD` (mặc định `0.9`) trong `.env`, hoặc tắt hẳn bằng
   `ML_AUGMENT_ENABLED=false` (xem `clustering/README.md` mục "ML augment"). Phối hợp với Nam
   trước khi đổi ngưỡng này trên bản deploy chính, vì đổi `signature` đại diện làm đổi `cluster_id`
   của các cụm đã gộp trước đó.

## Khi Ingestion quá tải / rớt log

1. Kiểm tra `GET /health` của `ingestion` — trả `degraded` (503) nghĩa là mất kết nối OpenSearch,
   không phải do quá tải CPU/RAM của chính `ingestion`.
2. Kiểm tra tài nguyên thật: `docker stats` trên máy chủ — OpenSearch thường là nơi tốn RAM nhất
   (`OPENSEARCH_HEAP` trong `.env`, mặc định `512m`).
3. Đo tải thật bằng `load-tests/locustfile.py` (`IngestionUser`) để biết throughput tối đa hiện
   tại trước khi kết luận "quá tải" — xem `load-tests/README.md` mục "Evidence cần ghi lại" cho
   số liệu đã đo (nếu có), phối hợp với Minh khi throughput đo được thấp hơn kỳ vọng.
4. Nếu log bị rớt do quarantine tăng bất thường (sai schema hàng loạt) — không phải do tải, mà do
   `demo-app` hoặc một client khác đang gửi payload sai `log-schema.json`. Phân biệt 2 nguyên nhân
   trước khi scale hạ tầng.

## Khi sửa cấu hình (`.env`, `Caddyfile`) mà không thấy hiệu lực

Phát hiện thật qua vận hành: `docker compose up -d` (không kèm `--force-recreate`) **không tự
khởi động lại container** nếu Compose không phát hiện thay đổi trong chính file
`docker-compose.yml` (image, biến môi trường khai báo trực tiếp...). Hai trường hợp hay gặp:

- **Đổi giá trị trong `.env`** (biến đọc qua `${VAR:-default}`) mà container đã chạy từ trước khi
  `.env` tồn tại hoặc thay đổi — container cũ vẫn giữ giá trị môi trường lúc nó được tạo. Sửa:
  `docker compose up -d --force-recreate <service>`.
- **Đổi nội dung file mount qua volume** (vd. `deploy/Caddyfile`) — container không tự đọc lại
  file dù nội dung trên đĩa đã đổi, vì tiến trình bên trong chỉ đọc file **lúc khởi động**. Sửa:
  `docker compose restart <service>` (không cần `--force-recreate`, chỉ cần khởi động lại tiến
  trình để nó đọc lại file).

Luôn verify lại bằng lệnh đọc trực tiếp cấu hình đang chạy thật, đừng tin vào việc "đã sửa file
là xong":
```bash
docker exec <container> env | grep <TEN_BIEN>      # xac nhan bien moi truong
curl -sI https://<domain>/<route-vua-sua>            # xac nhan route/HTTP status
```

## Liên hệ

| Module | Phụ trách |
|---|---|
| Demo app / Fault injection | Mạnh |
| Ingestion / Storage | Minh |
| Clustering / Anomaly score / Alert | Nam |
| Search / Incident View / Tích hợp / Deploy | Nghĩa |
