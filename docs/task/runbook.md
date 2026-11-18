# Runbook — Log Anomaly Explorer

> Sở hữu: Nghĩa (nhóm trưởng). Viết từ kinh nghiệm vận hành thật trên bản deploy (Docker Compose
> + gateway Caddy + Vercel) — không phải quy trình lý thuyết.

## Khi nhận được Alert

1. **Nhận alert** (webhook) — nội dung gồm `cluster_id`, `score`, `service`, `first_seen` và
   `trace_id` (một trace đại diện của cụm; xem payload chuẩn trong
   `docs/architect/contracts/api-contract.md` mục "Alert"). Nếu kênh nhận alert đã cấu hình link
   từ `trace_id` thì bấm thẳng vào đó để xem ngay một request lỗi cụ thể trên Jaeger, không cần
   qua bước 2–3.
2. **Mở Incident View**: đăng nhập web tại `/login` bằng tài khoản admin được cấp quyền,
   rồi mở `/clusters/{cluster_id}` với ID trong alert (route UI `/clusters/:id`) để xem
   signature, score và danh sách log liên quan. Chi tiết được tải từ `GET /clusters/{cluster_id}`.
   Nếu mở link khi chưa đăng nhập, web chuyển tới `/login` và quay lại Incident View sau
   khi đăng nhập thành công.
3. **Lần theo trace/request**: bấm icon ↗ cạnh một `trace_id` bất kỳ trong Incident View để mở
   trace thật trên Jaeger (`/jaeger/trace/{trace_id}`) — xem span nào trong request thực sự chậm
   hoặc lỗi, không chỉ đoán qua message.
   - Jaeger nằm sau **basic auth** của gateway: lần đầu trình duyệt hỏi tài khoản (xem mục
     "Truy cập Jaeger, fault injection và Swagger" bên dưới).
   - **Lưu ý**: trace mới được lưu trên disk bằng Badger, còn qua restart Jaeger hoặc toàn
     stack khi named volume còn nguyên. "Trace not found" có thể do quá TTL hoặc chưa từng
     được thu thập (ví dụ `demo-app` chưa cấu hình đúng `OTEL_EXPORTER_OTLP_ENDPOINT` lúc đó).
     Không kết luận request chưa xảy ra chỉ vì không thấy trace. Trace đã mất từ thời dùng
     memory storage không tự khôi phục được; có thể gọi lại `demo-app` để tạo trace demo mới.
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
6. **Tiếp nhận và đóng sự cố**. Bấm **Tiếp nhận** khi bắt đầu điều tra. Khi có kết luận,
   bấm **Đóng sự cố**, chọn **Sự cố thật** hoặc **Báo động giả**, ghi nguyên nhân hoặc
   lý do và kiểm tra lại khoảng thời gian. Nếu cùng cụm phát sinh log bất thường sau
   lúc đóng, Incident View hiển thị đợt mới khi tải lại. Đợt cũ vẫn được lưu.

Nam có thể xuất nhãn dương từ cùng OpenSearch bằng
`python -m clustering.evaluation.export_incidents --from <ISO-8601> --to <ISO-8601> --output <file.json>`.
Dùng `precision_recall.py --labels <file.json> --predictions <predictions.json>`
cho cùng khoảng đánh giá. Để đo recall, bổ sung cả sự cố được xác nhận độc lập
trong khoảng này mà detector đã bỏ sót.

## Vận hành Jaeger Badger và retention trace

- `jaeger-data` mount tại `/badger`; span nằm trong `/badger/data`, index trong `/badger/key`.
  Service `jaeger-init` tạo và cấp quyền các thư mục cho UID `10001` trước khi Jaeger chạy.
  `JAEGER_TRACE_TTL=168h` mặc định giữ span 7 ngày. Đổi TTL cần recreate Jaeger bằng
  `docker compose up -d jaeger`; chỉ `restart` không áp dụng environment hoặc mount mới.
- `docker compose restart jaeger`, `docker compose restart` và recreate container vẫn giữ
  dữ liệu đã ghi khi volume còn nguyên. `docker compose down` thông thường cũng giữ named
  volume; lần `up` sau cần dùng cùng Compose project để gắn lại đúng volume. **Không dùng
  `docker compose down -v`** khi cần giữ dữ liệu: lệnh đó xóa cả named volumes của stack,
  gồm Jaeger và OpenSearch. Không gắn một Badger volume cho nhiều Jaeger writer cùng lúc.
- Snapshot OpenSearch của **Task 04 không backup Jaeger Badger volume**. Trong phạm vi #107,
  trace **không có backup riêng**; mất volume/disk thì không có quy trình restore trace từ
  snapshot OpenSearch. Trace demo có thể tái tạo bằng cách gọi `demo-app`, ví dụ
  `/demo/simulate-error?rate=1&fault=runtime&seed=107` qua gateway với basic auth, rồi mở
  trace ID mới trong Incident View. Trace mới không khôi phục lại ID/nội dung trace đã mất.
- Theo dõi dung lượng disk: TTL giới hạn tuổi span, **không phải hard quota**; maintenance,
  compaction và tốc độ ingest ảnh hưởng dung lượng thực tế. Không xóa file Badger đang chạy
  để giải phóng disk. Xem TTL hiệu lực bằng:

  ```sh
  docker inspect "$(docker compose ps -q jaeger)" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^BADGER_SPAN_STORE_TTL='
  ```

  Xác định volume và mount thực (tên có tiền tố Compose project, không giả định tên cố định):

  ```sh
  cid=$(docker compose ps -q jaeger)
  docker inspect "$cid" --format '{{range .Mounts}}{{if eq .Destination "/badger"}}{{.Name}} {{.Source}}{{end}}{{end}}'
  ```

  Đo volume bằng helper read-only; thay `<volume-name>` bằng tên vừa đọc. Cách này dùng được
  cả khi mountpoint nằm trong Linux VM của Docker Desktop, không truy cập trực tiếp từ host:

  ```sh
  docker run --rm --user 0 \
    --mount type=volume,source=<volume-name>,target=/badger,readonly \
    --entrypoint /bin/sh caddy:2.8-alpine -c 'du -sh /badger; du -sk /badger'
  ```

  Ghi thời điểm, TTL, workload và số đo T0/T+24h cho Task 12; xem
  [evidence và hướng dẫn kiểm thử #107](../evidence/10-jaeger-badger/README.md).

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

5. Nếu nhận **429** từ `/ingest` hoặc `/ingest/batch`, kiểm tra `INGEST_RATE_LIMIT_RPS` (giới hạn mỗi tiến trình); client cần giảm nhịp, đọc `Retry-After` và tránh retry dồn dập. Batch 1–500 log giúp giảm request overhead nhưng không thay thế backpressure tập trung khi chạy nhiều instance.
6. Mở **Trạng thái hệ thống** trên web để đối chiếu `/health` của Query API, Ingestion và Demo App; màu xanh = HTTP 200 + `status=ok`, đỏ = degraded/không kết nối.
7. Với dữ liệu tăng nhanh, kiểm tra daily indices `logs-YYYY.MM.DD` và retention theo `RETENTION_DAYS`. Retention drop trọn ngày cũ, và drop legacy `logs` khi log mới nhất trong đó đã quá `RETENTION_DAYS` (log ghi `retention: giu index legacy ...` / `da drop index legacy ...`). Cần giữ legacy để backup/migrate thì đặt `RETENTION_DROP_LEGACY_INDEX=false` trước khi nó hết hạn. Không xóa `logs-quarantine` bằng daily retention.

## Khi AI Assistant không trả lời được

`GET /assistant/health` **luôn trả HTTP 200** — đây là một dòng thông tin trên trang "Trạng thái
hệ thống", không phải healthcheck của container (trả 503 sẽ khiến UI chỉ hiện "HTTP 503" thay vì
lý do thật). Vì vậy đọc field `status`, đừng đọc HTTP status; UI cũng dựa vào `status === "ok"`
nên hết quota vẫn hiện đỏ đúng. Endpoint này **không gọi** Azure OpenAI (trang này poll 15s/lần,
gọi thật sẽ tốn phí) — nó chỉ đọc cấu hình + kết quả **lần gọi thật gần nhất**, nên luôn kèm
`last_call_at` (UI hiện "Gọi Azure OpenAI lần cuối ..."). Dùng mốc đó để biết sự cố xảy ra từ khi
nào, và để phân biệt "chưa ai hỏi gì" với "hỏi rồi nhưng lỗi".

```bash
curl -s https://<domain>/assistant/health        # khong can dang nhap
```

| `status` | Nghĩa | Hành động |
|---|---|---|
| `ok` | cấu hình đủ, lần gọi gần nhất thành công (kèm `model`) | Không cần làm gì |
| `chưa cấu hình` | thiếu `AZURE_OPENAI_API_KEY` hoặc `AZURE_OPENAI_ENDPOINT` (lý do cụ thể trong `detail`) | Bổ sung vào `.env` rồi `docker compose up -d --force-recreate query-api` (xem mục dưới: đổi `.env` **không** tự có hiệu lực) |
| `kho hội thoại chưa sẵn sàng` | `query-api` khởi động khi OpenSearch chưa lên, nên index `assistant-conversations` chưa được tạo | Kiểm tra OpenSearch (`docker compose ps`), rồi `docker compose restart query-api` |
| `lỗi gọi gần nhất: <Lỗi>` | lần gọi Azure OpenAI thật gần nhất đã lỗi | Theo loại lỗi bên dưới |

Các `<Lỗi>` hay gặp (tên class của SDK, hiện nguyên văn trên UI):

1. **`RateLimitError`** — hết quota/TPM của deployment. Kiểm tra quota trên Azure Portal cho
   deployment `AZURE_OPENAI_DEPLOYMENT` (mặc định `gpt-5-mini`). Đây là lỗi hay gặp nhất khi demo
   nhiều lần liên tiếp; chờ hết cửa sổ tính quota là tự hết, không cần sửa gì.
2. **`APITimeoutError`** — một lần gọi vượt `AZURE_OPENAI_TIMEOUT_SECONDS` (mặc định `60`). Model
   dòng reasoning có thể suy luận rất lâu; hỏi ngắn/cụ thể hơn, hoặc giảm
   `ASSISTANT_REASONING_EFFORT` (mặc định `low`), hoặc giảm `ASSISTANT_MAX_TOOL_ROUNDS`
   (mặc định `2`). Tăng timeout là lựa chọn cuối — nó chỉ dịch chỗ treo sang người dùng.
3. **`PermissionDeniedError` / lỗi chặn theo vùng** — đã gặp thật: VM đặt ở vùng Azure Hong Kong
   bị OpenAI trực tiếp chặn theo khu vực địa lý. Cách giải quyết đã áp dụng: dùng **Azure OpenAI**
   (resource ở vùng không bị chặn) thay cho API OpenAI trực tiếp. Nếu tạo lại resource, kiểm tra
   vùng trước khi deploy model.
4. **`AuthenticationError`** — key đã rotate/hết hạn, hoặc `AZURE_OPENAI_ENDPOINT` trỏ sai
   resource. Lưu ý endpoint phải ở dạng `<endpoint>/openai/v1/` (xem
   `assistant/config.py::azure_openai_v1_base_url`) — dùng `api-version` cũ cố định sẽ khiến
   `reasoning_effort` và các tham số mới **bị âm thầm bỏ qua**, không báo lỗi gì.

Khi gửi câu hỏi mà UI báo lỗi, phân biệt 2 nhóm bằng **nội dung thông báo**:

- **`AI Assistant loi: <TênLỗi>`** — lỗi từ phía model/storage, đã được backend bắt và báo về
  (nhánh JSON trả 502, nhánh streaming gửi event `error`). Tra `<TênLỗi>` theo bảng trên.
- **`Luồng trả lời của AI Assistant bị ngắt giữa chừng.`** — stream SSE kết thúc mà không có event
  `conversation` cuối cùng. Đây **không phải** lỗi của model.

### Khi "luồng trả lời bị ngắt giữa chừng"

Dấu hiệu quyết định: **tải lại Incident View thấy câu trả lời đã có**. Nghĩa là backend đã chạy
xong trọn vẹn và lưu hội thoại, chỉ có đường truyền về browser bị cắt — đừng đi debug model hay
prompt. Đã gặp thật một lần, nguyên nhân là **lệch phiên bản giữa frontend và backend**: frontend
trên Vercel tự deploy ngay khi merge vào `main`, còn container trên VM vẫn chạy image cũ, nên
frontend gửi `Accept: text/event-stream` cho một backend chưa biết trả SSE. Cách xử lý: rebuild
đúng các container bị ảnh hưởng (xem mục kế tiếp).

Kiểm tra lệch phiên bản trước mọi thứ khác — nhanh và loại được nguyên nhân phổ biến nhất:

```bash
docker compose exec query-api grep -c "text/event-stream" query-api/src/assistant/router.py
# 0 hoac bao khong co file -> image cu, rebuild; >0 -> code da moi, xem buoc duoi
```

Nếu code đã mới, khoanh vùng hop nào cắt stream bằng cách chạy **cùng một request qua 3 chặng** và
so kết quả. Chặng nào kết thúc mà **không có** dòng `data: {"conversation":...}` chính là chặng cắt:

```bash
TOKEN=$(curl -s -X POST https://<domain>/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<admin>","password":"<pass>"}' \
  | grep -o '"token":"[^"]*"' | cut -d'"' -f4)

probe() {
  curl -N -s -X POST "$1/assistant/clusters/<cluster_id>/conversation/messages" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -H 'Accept: text/event-stream' -d '{"message":"Loi nay do dau?"}' \
  | while IFS= read -r l; do printf '[%s] %.120s\n' "$(date +%T)" "$l"; done
}

probe http://localhost:9002            # 1. thang query-api (bo qua Caddy + Vercel)
probe https://<domain>                 # 2. qua Caddy gateway
probe https://<app>.vercel.app/api     # 3. qua Vercel rewrite
```

Lưu ý khi đọc: stream có **khoảng lặng dài là bình thường** — vòng gọi tool đầu tiên không sinh
chữ nào, nên có thể im lặng tới `AZURE_OPENAI_TIMEOUT_SECONDS` giây trước byte đầu tiên (UI hiện
"AI đang điều tra…" kèm nút **Dừng**). Vercel cắt proxy tới origin ngoài nếu không nhận được dữ
liệu nào trong 120 giây, nên nếu chặng 3 chết mà chặng 1–2 đủ, hướng xử lý là gửi heartbeat định
kỳ trong lúc chờ (dòng comment `: ping` — client bỏ qua an toàn vì chỉ đọc dòng `data: `).

## Khi sửa cấu hình (`.env`, `Caddyfile`) hoặc merge code mà không thấy hiệu lực

Phát hiện thật qua vận hành: `docker compose up -d` (không kèm `--force-recreate`) **không tự
khởi động lại container** nếu Compose không phát hiện thay đổi trong chính file
`docker-compose.yml` (image, biến môi trường khai báo trực tiếp...). Ba trường hợp hay gặp:

- **Đổi giá trị trong `.env`** (biến đọc qua `${VAR:-default}`) mà container đã chạy từ trước khi
  `.env` tồn tại hoặc thay đổi — container cũ vẫn giữ giá trị môi trường lúc nó được tạo. Sửa:
  `docker compose up -d --force-recreate <service>`.
- **Đổi nội dung file mount qua volume** (vd. `deploy/Caddyfile`) — container không tự đọc lại
  file dù nội dung trên đĩa đã đổi, vì tiến trình bên trong chỉ đọc file **lúc khởi động**. Sửa:
  `docker compose restart <service>` (không cần `--force-recreate`, chỉ cần khởi động lại tiến
  trình để nó đọc lại file).
- **Merge PR xong, `git pull` trên VM nhưng chưa rebuild image** — code Python được `COPY` vào
  image lúc build, **không** mount volume, nên `git pull` một mình không đổi gì bên trong
  container đang chạy. Sửa: `docker compose up -d --build <service>` cho **từng service có code
  thay đổi**. Lưu ý `query-api` và `clustering` còn `COPY ingestion` (dùng chung
  `ingestion.src.storage`), nên một PR chỉ sửa `ingestion/` vẫn có thể cần rebuild cả 3.

  Đây là bẫy nguy hiểm nhất của bản deploy này, vì **frontend và backend không deploy cùng nhịp**:
  `web/` trên Vercel tự deploy ngay khi merge vào `main`, còn backend trên VM chỉ đổi khi có người
  rebuild. Khoảng lệch đó tạo ra lỗi khó đoán — đã gặp thật với AI Assistant (xem mục trên:
  frontend mới gửi `Accept: text/event-stream` cho backend cũ chưa biết trả SSE). Sau mỗi lần
  merge PR có đổi code backend, rebuild trước khi test UI, và xác nhận code đã thật sự vào
  container:
  ```bash
  docker compose exec <service> grep -c "<chuoi-moi-cua-PR>" <duong/dan/file.py>
  ```

  Nhưng đừng rebuild bằng chuỗi lệnh tay: `deploy/deploy.sh` (mục "Deploy và rollback" bên dưới)
  build đủ service, đặt `GIT_SHA` và tự kiểm `/health` thay cho cả bước xác nhận ở trên.

  Quên truyền `GIT_SHA` thì `version` là `unknown` — không phải lỗi, chỉ là không kiểm tra được.
  Trang **Trạng thái hệ thống** của web cũng so SHA này với SHA mà Vercel build và hiện cảnh báo
  khi hai bên lệch nhau, nên lỗi "frontend mới gọi backend cũ" không còn âm thầm.

Luôn verify lại bằng lệnh đọc trực tiếp cấu hình đang chạy thật, đừng tin vào việc "đã sửa file
là xong":
```bash
docker exec <container> env | grep <TEN_BIEN>      # xac nhan bien moi truong
curl -sI https://<domain>/<route-vua-sua>            # xac nhan route/HTTP status
```

## Deploy và rollback

```bash
cd ~/prj2
./deploy/deploy.sh main        # deploy ban moi nhat tren main
./deploy/deploy.sh caf04dc     # rollback: cung script, dua SHA cu
```

Script tự làm 5 việc mà làm tay hay quên: `git fetch`, đặt `GIT_SHA`, build **cả 4** service
Python (`query-api` và `clustering` đều `COPY ingestion`, nên không phải nhớ service nào phụ thuộc
service nào), nạp lại gateway, rồi chờ tối đa 60 giây để `/health` trả đúng `version == GIT_SHA`.
**Thoát mã khác 0 khi không khớp** — đó là lúc đừng đi test UI mà đọc `docker compose logs query-api`.

Ba điều cần biết:

- Script **không** đụng tới `jaeger` và `opensearch`. Jaeger giữ trace trong RAM nên recreate là
  mất hết; deploy không được phép xoá dữ liệu điều tra.
- Sau khi chạy, repo ở trạng thái **detached HEAD** tại đúng commit đã deploy. Đó là cố ý: VM không
  phải chỗ để code, và nó loại luôn bẫy "`git checkout main` nhưng local `main` đang cũ". Muốn
  xem đang ở đâu: `git rev-parse --short HEAD`.
- Script **từ chối chạy** nếu có file đã commit bị sửa tay trên VM, vì deploy như vậy tạo một bản
  không tái lập được từ git và `GIT_SHA` sẽ nói sai về code đang chạy. Sửa tay có chủ đích thì
  `git stash` trước. File untracked (venv, log, file evidence) không bị chặn — `.dockerignore` đã
  loại chúng khỏi build context.

**Bẫy: rollback về commit có trước `83dbc0d` sẽ xoá chính `deploy/deploy.sh`**, vì ở đó file chưa
tồn tại và `git checkout` dọn theo. Đã gặp thật ngày 2026-11-16 khi rollback về `caf04dc`. Cách
thoát, không cần script:

```bash
git checkout main && git pull --ff-only origin main
./deploy/deploy.sh main
```

Với các commit từ `83dbc0d` trở đi thì không gặp, vì script đã nằm trong mọi commit.

Build cả 4 image trên VM 2 vCPU mất vài phút và làm CPU tăng vọt → **đừng deploy sát giờ demo**.

## Truy cập Jaeger, fault injection và Swagger

Từ ngoài VM chỉ còn cổng 80/443 của gateway. Cổng `9000`/`9001`/`9002`/`16686` chỉ bind
`127.0.0.1`, nên các lệnh `curl http://localhost:9002/...` trong runbook này vẫn chạy, nhưng
**chỉ khi gõ trên chính VM**.

| Cần | Cách |
|---|---|
| Jaeger UI, `/demo/simulate-error` | `https://<domain>/jaeger/`, `https://<domain>/demo/...` — basic auth bằng `GATEWAY_BASIC_AUTH_USER` + mật khẩu gốc của `GATEWAY_BASIC_AUTH_HASH` trong `.env` trên VM (hỏi Nghĩa). `curl -u <user>:<pass> ...` |
| `/health`, `/ingestion/health`, `/demo/health` | Public, không cần auth — trang Trạng thái hệ thống đọc các route này |
| Swagger `/docs`, `/openapi.json` | Không còn public. `ssh -L 9002:localhost:9002 <user>@<vm>` rồi mở `http://localhost:9002/docs` |
| `POST /ingest` hoặc Locust từ máy khác | SSH tunnel tương tự cho cổng `9000`/`9002` |

Không có tài khoản nào thì `/jaeger` và `/demo/*` trả **401 cho mọi người** (không mở public);
nếu đúng mật khẩu mà vẫn 401, kiểm tra `docker exec <gateway> env | grep GATEWAY_BASIC_AUTH`.
Đổi mật khẩu: tạo hash mới (lệnh trong `.env.example`), sửa `.env` — hash phải bọc **nháy đơn**
vì có ký tự `$` — rồi `docker compose up -d --force-recreate gateway` (đổi biến môi trường cần
recreate, `restart` không đủ).

## Liên hệ

| Module | Phụ trách |
|---|---|
| Demo app / Fault injection | Mạnh |
| Ingestion / Storage | Minh |
| Clustering / Anomaly score / Alert | Nam |
| Search / Incident View / Tích hợp / Deploy | Nghĩa |
