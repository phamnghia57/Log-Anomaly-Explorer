# #108 — phần chạy đo của Nghĩa

**Đã làm:** chạy bộ 20 câu của Mạnh trên bản deploy thật, hai cấu hình, lấy token/chi phí/độ trễ
từ Langfuse, và một phép đo bổ sung để trả lời được câu "giữ `MAX_TOOL_ROUNDS` ở 1 hay 2".

**Không thuộc phần này:** chấm điểm. Nhóm quyết định dùng bản chấm của Codex (AI) ở
[ai-review/](ai-review/README.md) làm kết quả cuối thay cho hai người thật — rounds=1 **55/60**,
rounds=2 **56/60**. Bốn file `rater-*.template.csv` giữ nguyên làm template.

## 1. Cấu hình lúc đo

| Mục | Giá trị |
|---|---|
| Ngày đo | 2026-11-20 |
| VM | `log-anomaly-vps` (23.98.41.222) |
| `GIT_SHA` của query-api | `38defc3` |
| Deployment | `gpt-5-mini` (Azure OpenAI, UAE North) |
| `ASSISTANT_REASONING_EFFORT` | `low` |
| `ASSISTANT_MAX_OUTPUT_TOKENS` | `1200` |
| `AZURE_OPENAI_TIMEOUT_SECONDS` | `60` |
| Tool khả dụng | `get_trace` và các tool read-only trong `assistant/tools.py` |
| Cửa sổ lượt 1 | `2026-11-20T03:53:47.960354Z` .. `03:59:33.460484Z` |
| Cửa sổ lượt 2 | `2026-11-20T03:59:37.906960Z` .. `04:05:35.476779Z` |

**Ngữ cảnh được đóng băng:** `demo-app` stop trong suốt hai lượt (không có log mới). `clustering`
vẫn chạy — không ảnh hưởng vì cả 4 cụm golden đều `last_seen = 2026-11-14`, nằm ngoài cửa sổ 31
phút của worker nên `clusters_out=0` và record của chúng không bị ghi lại. Đã kiểm `last_seen` của
cả 4 cụm trước khi đo. Cả hai lượt dùng **cùng** `prepared/questions.json`.

Binding 4 cụm thật (xác minh trước bằng `prepare_assistant_golden.py`, snapshot ở `prepared/clusters/`):

| Nhóm | `cluster_id` | Số log |
|---|---|---|
| `value-422` | `a78b058d489d25cb` | 70 |
| `connection-502` | `d096e58268883c9d` | 44 |
| `timeout-504` | `bc2fad362a48590a` | 36 |
| `runtime-500` | `bca2eea604629975` | 70 |

## 2. Kết quả chạy

Cả hai lượt: **20/20 câu, 0 lỗi API**. Dữ liệu thô: [scores-round1.csv](scores-round1.csv),
[scores-round2.csv](scores-round2.csv).

## 3. Số liệu Langfuse

Lấy bằng **API** `GET /api/public/v2/observations?fields=core,basic,usage` (endpoint v1 đã bị
Langfuse bỏ từ 2026-11-16), không chép tay từ UI. Script:
[langfuse-summary.py](langfuse-summary.py). Kết quả:
[langfuse-summary.csv](langfuse-summary.csv), chi tiết từng câu:
[langfuse-per-question.csv](langfuse-per-question.csv).

Cách ghép generation với câu hỏi: mỗi generation thuộc về **câu gần nhất trước nó trên cùng
`sessionId`** (`sessionId` = `cluster_id`). Không ghép bằng "cửa sổ quanh `asked_at`" — 4 câu liên
tiếp dùng chung một cluster nên cửa sổ sẽ chồng lên câu sau; lần chạy đầu làm vậy cho coverage sai
12/20 và `model_latency` lớn hơn cả `api_latency`. Hai lượt phân biệt bằng **hai mốc thời gian
chính xác** mà runner in ra, vì chúng chỉ cách nhau 4,4 giây.

| Chỉ số | `MAX_TOOL_ROUNDS=1` | `MAX_TOOL_ROUNDS=2` | Chênh |
|---|---|---|---|
| Số câu | 20 | 20 | |
| Lỗi API | 0 | 0 | |
| Coverage telemetry | **20/20** | **20/20** | |
| Generation (lần gọi model) | 20 (1,0/câu) | **24** (1,2/câu) | +4 |
| Token vào / câu (TB) | 1 059 | **1 714** | **+61,8 %** |
| Token ra / câu (TB) | 784 | 890 | +13,5 % |
| Token tổng / câu (TB) | 1 843 | 2 604 | +41,3 % |
| **Chi phí / câu (TB)** | **0,001718 USD** | **0,001979 USD** | **+15,2 %** |
| Chi phí cả lượt 20 câu | 0,034355 USD | 0,039575 USD | +15,2 % |
| Độ trễ model TB | 7,73 s | 8,33 s | +7,8 % |
| **Độ trễ model p95** | **10,08 s** | **10,49 s** | +4,1 % |
| Độ trễ API đầu-cuối TB | 7,76 s | 8,36 s | +7,7 % |
| Độ trễ API đầu-cuối p95 | 10,11 s | 10,53 s | +4,2 % |

Tiền tệ: **USD**, giá do Langfuse tính (`totalCost`), gói `Standard`. p95 dùng **nearest rank**
(vị trí `ceil(0.95·n)` trong danh sách tăng dần, n = 20). Độ trễ model (Langfuse) và độ trễ API
đầu-cuối (runner) là hai đại lượng riêng, báo riêng như rubric yêu cầu — ở đây chúng gần như bằng
nhau, tức overhead của query-api ngoài lời gọi model chỉ ~0,03 s.

### Chi phí tăng ở đâu

`MAX_TOOL_ROUNDS=2` chỉ gọi tool ở **4 trên 20 câu**, nhưng token vào tăng **ở cả 20 câu**:

| Nhóm câu | Token vào TB, rounds=1 | rounds=2 |
|---|---|---|
| `value-422` | 891 | 1 563 |
| `connection-502` | 1 151 | 1 887 |
| `timeout-504` | 1 109 | 1 836 |
| `runtime-500` | 1 069 | 1 784 |
| `bad_schema` | 1 076 | 1 500 |

Nguyên nhân: với `rounds=1` vòng duy nhất **không gửi `tools`**
(`service.py`: vòng cuối bỏ `tools`), còn `rounds=2` gửi toàn bộ schema tool ở vòng đầu của **mọi**
câu. Tức ~650 token vào mỗi câu là tiền trả cho *khả năng* gọi tool, không phải cho lần gọi thật.

Bốn câu gọi tool đúng là câu `-03` của cả bốn nhóm fault — những câu yêu cầu đọc trace:

| Câu | Generation | Token vào | Chi phí USD |
|---|---|---|---|
| `value-422-03` | 2 | 2 310 | 0,0019063 |
| `connection-502-03` | 2 | 2 825 | 0,0017291 |
| `timeout-504-03` | 2 | 2 748 | 0,0024662 |
| `runtime-500-03` | 2 | 2 660 | 0,0021346 |

## 4. Hai lượt chính KHÔNG đủ để khuyến nghị — và vì sao

Cả **4/4** lần gọi `get_trace` ở lượt 2 đều trả **`trace not found`**. Nguyên nhân đã kiểm trên VM:

```
GET /jaeger/api/services -> ["jaeger-all-in-one", "query-api"]      # khong co "demo-web"
GET /jaeger/api/traces?service=demo-web -> 0 trace
BADGER_SPAN_STORE_TTL = 168h (7 ngay)
```

Bốn cụm golden từ **2026-11-14**; Jaeger chuyển sang Badger ở Task 10 với volume **mới**, nên span
cũ của `demo-app` không còn, và `demo-app` đang stop nên cũng không có span mới. Vậy lượt 2 bị đo
trong điều kiện tool **không thể** thành công: nó trả tiền cho tool mà không nhận lại gì.

Nếu dừng ở đây thì kết luận "rounds=2 đắt hơn 15 % mà vô ích" sẽ **sai** — sai vì tiền đề bị vỡ,
không phải vì cấu hình.

## 5. Phép đo bổ sung: khi trace CÒN tồn tại

Bật lại `demo-app`, bơm 60 request `fault=downstream` (signature `simulated downstream failure` —
**không** phải cụm golden nào, nên 4 cụm golden không bị đụng), xác minh **5/5** trace của log mẫu
có trong Jaeger, rồi hỏi đúng câu dạng `-03` hai lần cho mỗi cấu hình.
Script: [tool-rounds-fair.py](tool-rounds-fair.py). Kết quả thô:
[tool-rounds-fair.json](tool-rounds-fair.json). Cụm: `583498fff9a5c679`, score 60,0.

| Cấu hình | Gọi tool | Trả lời được HTTP status? | Độ trễ |
|---|---|---|---|
| `rounds=1`, lần 1 | không | **không** — "không thể xác định HTTP status" | 7,16 s |
| `rounds=1`, lần 2 | không | **không** — "KHÔNG THỂ xác định HTTP status" | 8,46 s |
| `rounds=2`, lần 1 | `get_trace` | **có** — `http_status: 500`, span `GET /api/items`, `duration_ms: 36.9`, 2 span lỗi | 9,63 s |
| `rounds=2`, lần 2 | `get_trace` | **có** — cùng kết quả | 8,76 s |

Ground truth của fault `downstream` là **HTTP 500**. `rounds=2` lấy đúng 500 từ trace **2/2 lần**;
`rounds=1` không lấy được **0/2 lần**, và còn nêu sai giới hạn của chính nó (xem mục 6).

## 6. Khuyến nghị cuối: **giữ `MAX_TOOL_ROUNDS = 2`**

Lý do bằng số:

- Giá phải trả: **+0,000261 USD/câu (+15,2 %)** và **+0,41 s ở p95 (+4,1 %)**. Với 20 câu là
  **+0,0052 USD** — không đáng kể.
- Đổi lại: những câu cần dữ liệu ngoài 5 log mẫu chỉ trả lời được ở `rounds=2`. Trên cụm có trace
  sống, `rounds=2` nêu đúng HTTP status **2/2**, `rounds=1` **0/2**.
- `rounds=2` **không** gây gọi tool tràn lan: chỉ 4/20 câu (20 %) dùng tới vòng tool, 16 câu còn
  lại trả lời thẳng từ log mẫu như system prompt yêu cầu.
- Đây là khuyến nghị **giữ nguyên mặc định đang có**, không phải đổi cấu hình.

Có một cách giảm chi phí mà phép đo này chỉ ra: ~650 token vào mỗi câu là schema tool gửi cho cả
20 câu dù chỉ 4 câu dùng. Nếu muốn tiết kiệm thì cắt bớt số tool gửi kèm hoặc rút gọn mô tả tool,
**không** phải hạ `MAX_TOOL_ROUNDS` xuống 1.

## 7. Dạng câu AI trả lời kém nhất — bản đọc sơ bộ của Nghĩa

Đây **không** phải điểm chính thức; hai người chấm vẫn phải chấm độc lập. Ghi lại để người chấm
đối chiếu:

1. **Câu cần trace / HTTP status (4 câu `-03`).** Là dạng yếu nhất rõ rệt. Ở `rounds=1` không bao
   giờ trả lời được; ở `rounds=2` chỉ trả lời được khi trace còn trong Jaeger. Hai lượt chính đều
   không đạt ground-truth status cho 4 câu này.
2. **Mô tả sai năng lực của chính nó.** Ở `rounds=1`, câu `timeout-504-03` và `value-422-03` trả
   lời đại ý *"Tôi không có quyền truy cập vào hệ thống APM/tracing"* — **sai**: hệ thống CÓ tool
   `get_trace`, chỉ là cấu hình `rounds=1` không cấp tool cho vòng duy nhất đó. Người chấm nên xem
   đây có vi phạm tiêu chí 3 ("không bịa thông tin không có trong dữ liệu") hay không.
3. **HTTP status nói chung.** Log của `demo-app` **không** ghi `http.status_code` (span có, log
   không), nên không có trace thì mọi cấu hình đều chỉ nêu được giới hạn. Đây là thiếu sót của
   **dữ liệu log**, không phải của AI — sửa bằng cách thêm `http.status_code` vào `metadata` khi
   `emit_log`, sẽ đáng giá hơn mọi tinh chỉnh prompt.

Trái lại, nhóm **`bad_schema` trả lời tốt**: 4/4 câu từ chối khẳng định đã có sự kiện quarantine,
dẫn message runtime thật, và **không** bịa `trace_id` hay số lượng quarantine — đúng đúng ý đồ
"kiểm tra ranh giới dữ liệu" của Mạnh.

## 8. Giới hạn của phép đo

- **Mỗi cấu hình chạy đúng 1 lượt.** Không có sai số lặp lại; chênh lệch độ trễ 0,4 s ở p95 nằm
  trong khoảng nhiễu của một lượt đơn, chỉ chênh lệch **token/chi phí** là xác định (do cấu trúc
  prompt, không phụ thuộc may rủi).
- Phép đo bổ sung mục 5 chỉ **1 câu × 2 lần × 2 cấu hình**, trên **1** cụm. Nó đủ để chứng minh
  khác biệt về *khả năng* (có/không đọc được trace) nhưng không đủ để kết luận về *tỉ lệ đúng*.
- Tool chỉ gọi được khi `JAEGER_QUERY_URL` trỏ đúng và trace còn trong TTL **7 ngày**. Với dữ liệu
  demo cũ hơn 7 ngày, `get_trace` sẽ luôn vô dụng — **cần biết trước khi demo**.
- Điểm/60 và số câu 3/3 lấy từ bản chấm AI ([ai-review/](ai-review/README.md)), không phải hai
  người thật chấm độc lập như rubric mô tả — nên không có số câu lệch giữa hai người chấm.
- 60 log `simulated downstream failure` của mục 5 đã cập nhật cụm `583498fff9a5c679` (không phải
  cụm golden). Snapshot của 4 cụm golden trong `prepared/clusters/` vẫn là bản lúc đo.
