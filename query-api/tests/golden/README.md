# Golden set cho AI Assistant — cách chạy đo

Hạ tầng cho Task 11. Chia việc: **Mạnh** soạn câu hỏi và chấm điểm, **Nghĩa** chạy đo và lấy số
từ Langfuse.

## 1. Soạn câu hỏi (Mạnh)

Copy `assistant-questions.example.json` thành `assistant-questions.json` trong chính thư mục này,
rồi điền 15–20 câu từ 5 loại fault đã biết nguyên nhân (bảng ở `docs/task/runbook.md` mục 5:
`value`/422, `connection`/502, `runtime`+timeout/504, `runtime`/500, `bad_schema`).

Mỗi mục cần `id`, `cluster_id`, `question`, và `expected` (đáp án đúng mong đợi, dùng lúc chấm).
`id` không được trùng. `cluster_id` phải là cụm **có thật** trên bản deploy — lấy từ
`GET /clusters` hoặc từ URL Incident View.

## 2. Chạy đo (Nghĩa)

Chạy **trên VM**, bên trong compose network: `opensearch` không publish port, và script cần gọi
được cả `query-api:8002` lẫn `opensearch:9200`.

```bash
cd ~/prj2

run_golden() {   # $1 = so vong tool, $2 = ten file ket qua
  echo "ASSISTANT_MAX_TOOL_ROUNDS=$1" 
  docker compose up -d --force-recreate query-api
  docker compose run --rm --no-deps \
    -e ASSISTANT_MAX_TOOL_ROUNDS="$1" \
    -e QUERY_API_USERNAME="$ADMIN_USER" -e QUERY_API_PASSWORD="$ADMIN_PASS" \
    -v "$PWD/query-api/tests/golden:/golden" \
    -v "$PWD/docs/evidence/11-assistant-golden-set:/out" \
    --entrypoint python query-api \
    /golden/run_assistant_golden.py --questions /golden/assistant-questions.json --output "/out/$2"
}

export ADMIN_USER=<admin> ADMIN_PASS=<mat-khau>
mkdir -p docs/evidence/11-assistant-golden-set

# Lan 1
sed -i 's/^ASSISTANT_MAX_TOOL_ROUNDS=.*/ASSISTANT_MAX_TOOL_ROUNDS=1/' .env
run_golden 1 scores-round1.csv

# Lan 2
sed -i 's/^ASSISTANT_MAX_TOOL_ROUNDS=.*/ASSISTANT_MAX_TOOL_ROUNDS=2/' .env
run_golden 2 scores-round2.csv

# Tra lai gia tri dang dung
sed -i 's/^ASSISTANT_MAX_TOOL_ROUNDS=.*/ASSISTANT_MAX_TOOL_ROUNDS=2/' .env
docker compose up -d --force-recreate query-api
```

Biến `ASSISTANT_MAX_TOOL_ROUNDS` được đọc **lúc import** `assistant/config.py`, nên phải sửa
`.env` rồi `--force-recreate query-api`; đặt biến cho riêng container chạy script không có tác
dụng — nó chỉ chạy script, còn model do `query-api` gọi.

Xác nhận cấu hình đã vào đúng container **trước mỗi lần chạy**:

```bash
docker compose exec query-api env | grep ASSISTANT_MAX_TOOL_ROUNDS
```

Script tự xoá hội thoại cũ của mỗi cụm trước khi hỏi (`DELETE` doc trong
`assistant-conversations`), vì 1 cụm chỉ có 1 hội thoại: không xoá thì câu sau thừa hưởng lịch sử
câu trước, token tăng dần và con số "chi phí trung bình mỗi câu" mất ý nghĩa. Muốn giữ lịch sử
thì thêm `--keep-history`.

`--delay` mặc định 10 giây giữa các câu. `RateLimitError` là lỗi hay gặp nhất khi gọi liên tiếp
(xem `docs/task/runbook.md`), đừng hạ xuống 0. Câu nào lỗi được ghi vào cột `error` và script vẫn
chạy tiếp — không mất cả lượt đo vì một câu.

## 3. Lấy số từ Langfuse (Nghĩa)

Dòng cuối của script in ra cửa sổ thời gian UTC của lượt chạy. Lọc đúng cửa sổ đó trên
[Langfuse](https://jp.cloud.langfuse.com), rồi lấy cho **mỗi lượt chạy**: token vào, token ra,
chi phí, độ trễ **trung bình và p95**. Xuất ra `docs/evidence/11-assistant-golden-set/langfuse-summary.csv`.

Trace có tag `log-anomaly-explorer` + `incident-assistant`, và `session_id` là `cluster_id`.
Hai lượt chạy phân biệt bằng **thời gian**, không phải bằng tag — nên đừng chạy hai lượt chồng nhau.

## 4. Chấm điểm (Mạnh + 1 người nữa)

Mở `scores-round1.csv` / `scores-round2.csv`, thêm 3 cột 0/1 cho mỗi câu (tổng 3 điểm/câu):

1. nêu đúng **tầng lỗi / HTTP status**;
2. **trích dẫn được bằng chứng thật** (`trace_id` hoặc message có trong log);
3. **không bịa** thông tin không có trong dữ liệu.

Hai người chấm độc lập, so kết quả, ghi lại **số câu lệch** rồi thảo luận chốt.

## 5. Viết kết quả

Vào `query-api/README.md` mục "AI Assistant — chất lượng đo được": bảng điểm/60 cho cả hai cấu
hình, chi phí trung bình mỗi câu, độ trễ p95, khuyến nghị cuối giữ `MAX_TOOL_ROUNDS` ở 1 hay 2
kèm lý do bằng số, và 2–3 dạng câu hỏi AI trả lời kém nhất.
