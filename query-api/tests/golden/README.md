# Golden set cho AI Assistant — cách chạy đo

Hạ tầng cho Task 11. Chia việc: **Mạnh** soạn câu hỏi và chấm điểm, **Nghĩa** chạy đo và lấy số
từ Langfuse.

## 1. Bộ 20 câu và gắn cluster thật (Mạnh bàn giao, Nghĩa chuẩn bị trên VM)

`assistant-questions.json` có 20 câu, 4 câu mỗi nhóm `value-422`, `connection-502`,
`timeout-504`, `runtime-500`, `bad_schema`. Mỗi câu có `id`, `category`, `cluster_ref`,
`cluster_id`, `question`, `expected`; `expected` chỉ dành cho người chấm, không gửi cho model.
ID trong catalog là `null` có chủ đích: chưa có bằng chứng trên bản deploy để gắn ID.
Runner từ chối catalog chưa gắn ID; file example cũ vẫn dùng được sau khi điền ID thật.

`bad_schema` bị ingestion đưa vào quarantine, không sinh cluster và Assistant không có tool
đọc quarantine. Bốn câu này dùng cluster `runtime-500` làm ngữ cảnh đối chứng để kiểm tra
AI nêu thiếu bằng chứng; chúng **không đo khả năng điều tra trực tiếp quarantine**.
Không tạo cluster giả cho bad_schema. Xem [rubric](../../../docs/evidence/11-assistant-golden-set/RUBRIC.md).

Lấy bốn ID khác nhau từ `GET /clusters` hoặc Incident View, cho bốn fault đầu. Chuẩn bị
cụm demo dành riêng cho golden; runner sẽ xóa hội thoại của các cụm này. Script chuẩn bị
chỉ đăng nhập và GET cluster, không gọi model hoặc ghi log/cluster. Nó xác minh 1–5 log
trả về thuộc 5 `log_ids` đầu (ngữ cảnh ban đầu của Assistant), có message và error_type
đúng `_inject_fault`; cụm bị ML gộp lẫn loại hoặc đã mất log sẽ bị từ chối.

Chạy trên VM trong compose network, từ gốc repo:

```bash
export ADMIN_USER='replace-with-admin' ADMIN_PASS='replace-with-password'
mkdir -p docs/evidence/11-assistant-golden-set
cp query-api/tests/golden/cluster-bindings.example.json \
  docs/evidence/11-assistant-golden-set/cluster-bindings.local.json
# Dien 4 ID that vao file local tren; khong dien mat khau/API key vao file.

docker compose run --rm --no-deps \
  -e QUERY_API_USERNAME="$ADMIN_USER" -e QUERY_API_PASSWORD="$ADMIN_PASS" \
  -v "$PWD/query-api/tests/golden:/golden:ro" \
  -v "$PWD/docs/evidence/11-assistant-golden-set:/out" \
  --entrypoint python query-api /golden/prepare_assistant_golden.py \
  --bindings /out/cluster-bindings.local.json --output /out/prepared
```

Output gồm `prepared/questions.json`, bốn snapshot `prepared/clusters/*.json` và
`prepared/manifest.json` (UTC, base URL không chứa credentials, bindings, SHA-256).
Thư mục tồn tại sẽ bị từ chối để giữ bằng chứng cũ. Chỉ dùng HTTP(S) URL không có
userinfo/query/fragment trong `QUERY_API_HOST`; credentials dùng biến riêng như trên.
Lỗi 401/404/5xx, log rỗng/sai loại/trộn service đều dừng trước khi tạo output.
Chưa chạy script này thành công thì trạng thái binding vẫn là **pending**.

## 2. Chạy đo (Nghĩa)

Chạy **trên VM**, bên trong compose network: `opensearch` không publish port, và script cần gọi
được cả `query-api:8002` lẫn `opensearch:9200`.

```bash
cd ~/prj2

original_rounds=$(docker compose exec -T query-api printenv ASSISTANT_MAX_TOOL_ROUNDS)
# Ghi original_rounds vao evidence truoc khi thay doi.

run_golden() {   # $1 = gioi han lan goi model, $2 = ten file ket qua
  ASSISTANT_MAX_TOOL_ROUNDS="$1" docker compose up -d --force-recreate query-api || return
  actual_rounds=$(docker compose exec -T query-api printenv ASSISTANT_MAX_TOOL_ROUNDS) || return
  if [ "$actual_rounds" != "$1" ]; then
    echo "Sai cau hinh server: expected=$1 actual=$actual_rounds" >&2
    return 1
  fi
  docker compose run --rm --no-deps \
    -e ASSISTANT_MAX_TOOL_ROUNDS="$1" \
    -e QUERY_API_USERNAME="$ADMIN_USER" -e QUERY_API_PASSWORD="$ADMIN_PASS" \
    -v "$PWD/query-api/tests/golden:/golden:ro" \
    -v "$PWD/docs/evidence/11-assistant-golden-set:/out" \
    --entrypoint python query-api \
    /golden/run_assistant_golden.py --questions /out/prepared/questions.json --output "/out/$2"
}

# ADMIN_USER/ADMIN_PASS da export o buoc chuan bi. Giu file cu truoc khi retry.

# Lan 1
run_golden 1 scores-round1.csv

# Lan 2
run_golden 2 scores-round2.csv

# Tra lai gia tri container truoc khi do; .env khong bi sua.
ASSISTANT_MAX_TOOL_ROUNDS="$original_rounds" docker compose up -d --force-recreate query-api
```

Biến `ASSISTANT_MAX_TOOL_ROUNDS` được đọc **lúc import** `assistant/config.py`, nên phải
truyền override cho Compose lúc `--force-recreate query-api` như trên (hoặc sửa `.env`
rồi recreate). Đặt biến cho riêng container chạy script không có tác dụng lên server —
nó chỉ chạy script, còn model do `query-api` gọi.

Xác nhận cấu hình đã vào đúng container **trước mỗi lần chạy**:

```bash
docker compose exec query-api env | grep ASSISTANT_MAX_TOOL_ROUNDS
```

Script tự xoá hội thoại cũ của mỗi cụm trước khi hỏi (`DELETE` doc trong
`assistant-conversations`), vì 1 cụm chỉ có 1 hội thoại: không xoá thì câu sau thừa hưởng lịch sử
câu trước, token tăng dần và con số "chi phí trung bình mỗi câu" mất ý nghĩa. Muốn giữ lịch sử
thì thêm `--keep-history`.

HTTP 404 khi reset nghĩa là chưa có hội thoại; các lỗi reset khác được ghi vào `error`
và câu đó không gọi model. `--keep-history` không dùng cho phép so sánh chuẩn của #108.
Đường dẫn index/cluster được URL-encode; lỗi một câu không bỏ mất các dòng đã thu được.

`--delay` mặc định 10 giây giữa các câu. `RateLimitError` là lỗi hay gặp nhất khi gọi liên tiếp
(xem `docs/task/runbook.md`), đừng hạ xuống 0. Câu nào lỗi được ghi vào cột `error` và script vẫn
chạy tiếp — không mất cả lượt đo vì một câu.

`MAX_TOOL_ROUNDS=1` thực tế gọi model một lần **không cung cấp tool**. `=2` cho phép một
lần model yêu cầu tool, thực thi các tool của lần đó rồi gọi model lần cuối để trả lời.
Không mô tả phép đo là một vòng so với hai vòng tool thực thi.

Trước mỗi lượt, lưu kết quả kiểm tra env container vào evidence cùng deployment/model,
reasoning effort, max output tokens, timeout, Git SHA/image và bộ tool khả dụng.
Dùng cùng `prepared/questions.json` và ngữ cảnh cho cả hai lượt. Nghĩa bố trí cửa sổ demo
riêng, tạm dừng nguồn bơm log và cập nhật clustering sau khi chuẩn bị đủ cụm để ngữ cảnh
không đổi, rồi khôi phục sau khi đo; tránh traffic Assistant khác trong lúc đo.
Nếu dữ liệu/config thay đổi giữa hai lượt thì chưa dùng chúng để khuyến nghị cấu hình.

## 3. Lấy số từ Langfuse (Nghĩa)

Dòng cuối của script in ra cửa sổ thời gian UTC của lượt chạy. Lọc đúng cửa sổ đó trên
[Langfuse](https://jp.cloud.langfuse.com), rồi lấy cho **mỗi lượt chạy**: token vào, token ra,
chi phí, độ trễ **trung bình và p95**. Xuất ra `docs/evidence/11-assistant-golden-set/langfuse-summary.csv`.

Trace có tag `log-anomaly-explorer` + `incident-assistant`, và `session_id` là `cluster_id`.
Hai lượt chạy phân biệt bằng **thời gian**, không phải bằng tag — nên đừng chạy hai lượt chồng nhau.

Giữ export thô và ghép từng câu theo `cluster_id` + `asked_at`/cửa sổ lượt đo, xác minh đủ
các generation thuộc lượt hỏi. **Cộng** input/output token, cost và generation latency của
các lần gọi model thuộc cùng câu trước khi tính trung bình/p95 trên các câu; không coi từng
generation là một câu. Ghi currency và model pricing từ Langfuse; không điền giá ước đoán
khi cost bị thiếu. P95 dùng nearest rank (vị trí `ceil(0.95*n)` trong danh sách tăng dần).
`latency_s` của runner là thời gian API đầu cuối, phải báo riêng với latency model Langfuse.
Generation của câu lỗi nếu có vẫn được tính chi phí và công bố coverage; thiếu telemetry
thì đánh dấu pending. Thiếu hoặc trùng mapping generation không được âm thầm loại bỏ.

## 4. Chấm điểm (Mạnh + 1 người nữa)

Giữ nguyên `scores-round1.csv` / `scores-round2.csv` là output thô của runner. Hai người
sao chép file `rater-{a,b}-round{1,2}.template.csv` sang file chấm riêng, ghi danh tính thật,
`answer_ref` tới dòng câu trả lời và ba cột 0/1 (tổng 3 điểm/câu):

1. nêu đúng **tầng lỗi / HTTP status**;
2. **trích dẫn được bằng chứng thật** (`trace_id` hoặc message có trong log);
3. **không bịa** thông tin không có trong dữ liệu.

Hai người chấm độc lập trước khi xem bảng của nhau. Điểm để trống nghĩa là **chưa chấm**.
Xem [quy tắc chấm và chốt bất đồng](../../../docs/evidence/11-assistant-golden-set/RUBRIC.md),
ghi số câu lệch riêng từng cấu hình và lưu hai bản gốc cùng bảng adjudication.

## 5. Viết kết quả

Vào `query-api/README.md` mục "AI Assistant — chất lượng đo được": bảng điểm/60 cho cả hai cấu
hình, chi phí trung bình mỗi câu, độ trễ p95, khuyến nghị cuối giữ `MAX_TOOL_ROUNDS` ở 1 hay 2
kèm lý do bằng số, và 2–3 dạng câu hỏi AI trả lời kém nhất.

Hiện chỉ hoàn thành phần câu hỏi/quy trình bàn giao. Binding thật, hai lượt Azure,
Langfuse, hai người chấm và khuyến nghị cấu hình đều **pending**; xem
[checklist evidence](../../../docs/evidence/11-assistant-golden-set/README.md).
