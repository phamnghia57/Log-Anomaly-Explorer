# BT3 — VT-013: Undo Assistant Send và Contract Testing

**MSSV:** 23001904 · **Nhóm:** SE2026-T04 · **Dự án:** AI-06 — Log Anomaly Explorer

**Nhánh:** `feat/vt013-undo-manhpd` · **Ngày tổng hợp:** 2026-11-09 (Asia/Saigon)

**Kết luận:** Bằng chứng thực nghiệm hỗ trợ tính đúng chức năng của Undo và bảo vệ phiên bản trong phạm vi kiểm thử. **NFR hiệu năng NOT MET.** Quyết định kỹ thuật là Option A: giữ nguyên production; không tối ưu hoặc thử A/B. Báo cáo phục vụ bài tập cá nhân, không đề nghị merge.

Kết quả dưới đây được tổng hợp từ logs, JUnit và raw artifacts đã lưu. Các lần chạy bằng fake transport, OpenSearch thật và browser được phân biệt; không coi việc tổng hợp tài liệu là một lần kiểm thử độc lập.

## 1. Bài toán, phạm vi và đặc tả

Assistant Send được chọn vì hành vi append ở giao diện được thực hiện bằng **unconditional replacement của toàn bộ conversation document** tại baseline. Nếu hai request cùng đọc H, request A ghi H+A thành công rồi B ghi H+B, cập nhật A bị mất dù cả hai có thể trả thành công. Đây là lost update do read–modify–write thiếu precondition, không phải chức năng Delete. Một lượt còn có thể chứa tool messages nên không thể Undo bằng cách xóa hai messages cuối. Snapshot trước Send hỗ trợ phục hồi chính xác; CAS/create-only ngăn overwrite một phiên bản đã thay đổi. [Baseline và call path](plan.md#1-specification-verified-contracts-and-invariants); [T-14 RED](evidence/red/README.md) ghi hai Send cùng 200/hai commit, [I-05](evidence/integration/test-results.md) kiểm chứng biện pháp bảo vệ trên server thật.

Rủi ro chính của đề: dữ liệu rỗng/giá trị biên vượt validation. Kỹ thuật bắt buộc: contract testing. Mutation bắt buộc: nuốt exception và trả dữ liệu mặc định. NFR: 60 tác vụ Undo được xác thực đồng thời, p95 ≤ 2.0 giây theo protocol đã duyệt; không dùng latency Azure Send để thay thế chỉ số này.

Năm AC giữ nguyên ý nghĩa từ [đặc tả](plan.md#acceptance-criteria--exactly-five):

| AC | Điều kiện chấp nhận được đo |
|---|---|
| AC-01 | Undo hiện hành khôi phục messages sâu bằng H, kể cả thứ tự/timestamps/null/tool fields; GET/restart API giữ restoration; snapshot một mức bị tiêu thụ; Undo đầu lưu [] với revision mới |
| AC-02 | Missing/null/non-string/empty/whitespace/over-4000 bị 422 trước generation/write; meaningful 1 và 4000 Unicode code points hợp lệ |
| AC-03 | Malformed revision 422; stale revision 409; rejection không đổi messages/snapshot/revision |
| AC-04 | Read/write/mapping failure là lỗi/503, không empty success; missing index là storage failure; definite pre-write failure giữ state; designated test kill swallowed-exception mutant |
| AC-05 | Mutation dựa cùng persisted version có tối đa một commit; loser 409; kiểm Send/Send, Undo/Undo, Send/Undo và first creation |

**Invariant:** mutation chỉ commit trên đúng phiên bản đã đọc; messages và snapshot phải commit nguyên tử. Empty history hợp lệ khác storage failure. Phạm vi là một mức Undo, shared-admin theo cluster, bền qua restart API; không redo, sender-only Undo hoặc dependency production mới.

## 2. Kiến trúc và contract thực hiện

Call path: `AssistantPanel` → React Query → Bearer API client → Assistant router → repository → OpenSearch. Send đọc history, chạy generation/tools rồi lưu; Undo không gọi AI/tool. Source: [router](../../../query-api/src/assistant/router.py), [repository](../../../query-api/src/assistant/storage.py), [hooks](../../../web/src/lib/queries.ts), [panel](../../../web/src/components/incident/AssistantPanel.tsx).

| Endpoint / request | HTTP thành công / contract |
|---|---|
| GET `/assistant/clusters/{id}/conversation` | 200 `{cluster_id,messages,revision,undo_available}` |
| POST `.../conversation/messages`, `{"message":"text"}` | 200, toàn bộ history sau completed Send và revision server |
| POST `.../conversation/undo`, `{"expected_revision":"1:0"}` | 200, history restored, revision mới, `undo_available:false` |

Send dùng strict string, độ dài raw 1–4000, reject whitespace-only và extra fields; accepted API text không bị trim. Revision canonical ASCII `primary_term:seq_no`, term ≥ 1, seq ≥ 0, mỗi thành phần ≤ 9223372036854775807; client coi token opaque. Absence có revision null; persisted [] có revision thật. Snapshot không lộ trong response.

401: JWT thiếu/sai; 404: cluster không tồn tại; 422: validation; 409: `revision_conflict` hoặc `nothing_to_undo`; 503: persistence; 502: generation. Undo so revision trước snapshot availability. Timeout/lost response có thể xảy ra sau commit: GET reconcile, không khẳng định storage chắc chắn chưa đổi. [API contract](../../architect/contracts/api-contract.md), [stored schema](../../architect/contracts/assistant-conversation-schema.json).

Repository dùng create-only khi absent, `if_seq_no` + `if_primary_term` khi update; không unconditional fallback. Send lưu `H+T` và `undo.messages=H` cùng document. Undo lưu H, tiêu thụ snapshot, giữ `created_at`, đổi `updated_at` và revision. Legacy đọc được; strict mapping chỉ bổ sung `undo`; Dockerfile copy schema runtime. [Source review](evidence/integration/review.md#persistence-contract-and-invariant).

Frontend chỉ thay cache bằng response được server xác nhận, không đoán turn là hai messages, không optimistic deletion/client revision. Pending Send/Undo khóa hai action; 409/503/network dùng GET reconciliation, không tự retry mutation. Stop vẫn cancellation, không server-side Undo. [Frontend review](evidence/frontend/README.md#contracts-explained-before-implementation).

## 3. Quy trình test-first và review AI

Quy trình: Spec → RED → GREEN → real integration → frontend → mutation → quality → performance. Contract/invariant được xác định trước implementation; RED chạy trên production chưa có Undo. Logs thất bại và corrections của test/tooling được giữ, phân biệt với lỗi sản phẩm.

| Nhận định/đề xuất AI cần sửa | Căn cứ và quyết định review |
|---|---|
| Đã phân biệt document absence với read failure | Baseline blanket 404 suppression nhầm missing index thành None; T-12 RED phát hiện. Chỉ genuine document absence là None; lỗi index/transport thành StorageError/503. Real I-07 xác nhận envelope thật |
| Opaque revision ≤128 ký tự là đủ | Chưa định nghĩa seq zero, numeric bounds, metadata và create race. Chốt canonical term:seq, CAS/create-only, ConflictError → 409; T-08/09/10 và I-05/06 kiểm chứng |
| Chỉ mở rộng fake cũ | Fake cũ bỏ qua CAS arguments và alias dữ liệu; sửa mô hình transport có control tests, sau đó real integration làm authority cho persistence |

Source và hệ quả của các corrections ở [plan §2](plan.md#2-review-and-corrections-to-the-previous-ai-proposal), [AI log](ai-usage-log.md). Lỗi alias của dữ liệu test được sửa bằng deepcopy, giữ equality assertion; F-10 tái hiện logout/cache race trước khi thêm session check. [GREEN](evidence/green/README.md#diagnosed-failure-retained-for-review), [frontend](evidence/frontend/README.md#diagnosed-failures-and-corrections).

## 4. Kết quả kiểm chứng chức năng và mutation

Kết quả lịch sử được đối chiếu artifact; các rerun không được cộng thành unique cases. [Traceability và commit SHAs](traceability.md).

| Phạm vi | Kết quả đã ghi / căn cứ |
|---|---|
| Backend RED, real routes/repository + fake transport | 10 FAIL/4 PASS; legacy 24 PASS. 10 lỗi là assertion contract, không collection/setup. [RED](evidence/red/README.md) |
| Backend GREEN | 14 focused + 24 regression + 52 additional = 90 PASS; combined 90 PASS là rerun cùng cases. [GREEN](evidence/green/README.md), [JUnit](evidence/green/combined-backend.junit.xml) |
| Real OpenSearch 2.17.1 | 13/13 PASS: lifecycle, exact tool history, empty first Undo, API restart, CAS/create races, missing index, mapping/legacy, read/write failures/auth. [Integration](evidence/integration/test-results.md) |
| Docker Python 3.11.18 | 103/103 PASS = cùng 13 real + 90 fake-backed; Query API build và runtime schema probe exit 0. [Integration README](evidence/integration/README.md) |
| Frontend | RED 37 FAIL + F-10 riêng 1 FAIL; final 38 targeted, 140 full PASS. Typecheck/lint/build exit 0, lint còn 9 warning cũ. [Frontend](evidence/frontend/README.md) |
| Real browser | 1 unique Chrome scenario PASS, login/Send/Undo/reload và raw persisted equality; không intercept API. [E2E](evidence/frontend/e2e-results.json) |
| M-01 | Baseline 90 PASS; mutant 86 PASS/4 FAIL; restored/final mỗi lần 90 PASS. [Mutation](evidence/mutation/README.md) |

Contract oracle kiểm status/schema, không generation/write khi invalid, messages/snapshot/revision đã lưu và state của winner, thay vì chỉ private helper. Boundary-value analysis dùng length 0/1/3999/4000/4001, term 1, seq 0, max/overflow; equivalence partitioning tách absent/empty/failure, meaningful/whitespace/wrong type, current/stale/malformed token. Mapping và SDK errors được kiểm thật, không suy ra từ fake.

M-01 thay generic read handler từ raise StorageError thành return None trong detached worktree. T-11, T-22 và hai metadata cases nhận **409 thay 503**, kill mutant bằng assertion có sẵn. CAS vẫn chặn create đè document; không ghi nhận overwrite hay HTTP 200. Ba T-12 vẫn PASS vì typed missing-index handler không đổi. Source hash phục hồi khớp bản gốc, temp worktree được xóa. [Diff](evidence/mutation/mutation.diff), [hashes/results](evidence/mutation/results.json).

## 5. Coverage, flakiness và khoảng trống

| Module | Line coverage | Branch coverage |
|---|---|---|
| `assistant/storage.py` | 130/141 = 92.20% | NOT MEASURED |
| `assistant/router.py` | 90/99 = 90.91% | NOT MEASURED |
| `web/src/lib/api.ts` | 51/51 = 100% | 52/54 = 96.29% |
| `web/src/lib/queries.ts` | 32/36 = 88.88% | 13/17 = 76.47% |
| `AssistantPanel.tsx` | 58/60 = 96.66% | 65/73 = 89.04% |

Nguồn: [quality README](evidence/quality/README.md#coverage-and-its-limits), [Python](evidence/quality/python-coverage.json), [frontend](evidence/quality/frontend-coverage-summary.json). Python stdlib trace là statement-line approximation gồm worker threads; không đo branches. V8 source-map chỉ ba modules, chạy 140 unit/component cases với mock HTTP; không cộng browser execution vào coverage.

Flaky review: 400/400 fake-backed race executions PASS (4 variants × 100, barrier, không sleep/retry); backend reverse order 90, focused 14, repo 6 PASS; frontend hai shuffle seeds mỗi lần 140 PASS. Mười browser executions thực trên disposable infrastructure PASS; 10 Docker preflight failures và 3 config failures trước collection giữ riêng, không tính PASS hay che bằng retries. [Quality results](evidence/quality/README.md#scheduling-shared-state-and-test-order), [final summary](evidence/quality/final-summary.json).

Sampling chưa phát hiện application flake, không chứng minh zero flakiness. P0 coverage gate **chưa đầy đủ**: malformed storage/identity/pre-write schema, configuration/generation errors và Send/logout/401 còn gaps. TLS, node failover, lost response sau commit, Node LTS, cross-browser và live Azure chưa đủ evidence. [Risk matrix](evidence/quality/risk-matrix.json).

## 6. Performance: NFR NOT MET và quyết định kỹ thuật

Protocol duyệt: 60 authenticated workers, barrier gồm coordinator, histories 0/2/100, 1 KiB/non-null message, 5 warm-up + 50 measured rounds/lớp. Seed/login/Send rearm/raw GET validation ngoài timing; timer sau barrier bao gồm POST, response và decode JSON. p95 nearest rank trên từng successful measured request, không average round p95; errors/warm-up retained riêng; contention 409 không trộn vào latency success. [Protocol và raw evidence](evidence/performance/README.md).

| History | Successful / measured | p95 (ms) | Lỗi | SLO |
|---|---|---|---|---|
| 0 | 1139/1140; chưa đủ 3000 | 2097.897 | 1 ReadError, restoration chưa xác nhận | **NOT MET** |
| 2 | 3000/3000 | 2077.965 | 0 | **NOT MET** |
| 100 | 3000/3000 | 2602.975 | 0 | **NOT MET** |

Nguồn: [summary.json](evidence/performance/summary.json), [comparison.csv](evidence/performance/comparison.csv), [initial raw](evidence/performance/samples.jsonl), [continuation raw](evidence/performance/continuation/samples.jsonl). Tổng 7140 measured attempts, 7139 success và 900 warm-up riêng. Mọi successful measured Undo khớp persistence. Initial run dừng ở ReadError (exit 1); H0 throughput/cause text/raw failed document không được lưu, không suy đoán data loss. Continuation trên instance mới chỉ chạy H2/H100 (exit 0 là completion, không compliance). Không retry H0 để thay kết quả xấu.

Chuỗi contention trong summary dẫn xuất bị mojibake; [results UTF-8 gốc](evidence/performance/continuation/results.json) giữ đúng Unicode/1024 byte. Reporter đọc theo default encoding; locale đã kiểm là cp1252. Raw p95/hashes vẫn khớp; discrepancy trình bày không được dùng làm bằng chứng persistence corruption.

Real contention riêng Undo/Undo và Send/Undo mỗi cặp một 200/một 409, persisted winner đúng; Undo thắng cả hai observed pairs. Backend 90/90 PASS sau measurement. [Summary](evidence/performance/summary.json), [regression JUnit](evidence/performance/backend-regression.junit.xml).

Môi trường đo: Windows shared host, Python 3.14.6, một Uvicorn worker, OpenSearch 2.17.1 single-node/one-shard, heap 512 MiB, container 2 GiB, tmpfs, refresh interval 1s. Resource snapshots ngoài timed rounds, không profile hay peak sampling. H100 response khoảng 109 kB; workloads compressible. Source `refresh="wait_for"`, sync execution và thread/pool defaults gợi ý refresh wait/queue/serialization, **chưa chứng minh bottleneck**. [Settings](evidence/performance/continuation/conversation-settings.json), [environment/limits](evidence/performance/README.md#isolation-environment-and-resources).

**Quyết định:** chọn A, giữ implementation và kết luận NOT MET. B đổi deployment benchmark chưa chứng minh lợi ích; C tối ưu production thiếu causal evidence và có regression risk. Không đổi threshold, CAS, durability, validation hoặc error propagation. Tính đúng chức năng trong phạm vi đo không đồng nghĩa tuân thủ performance NFR.

## 7. AI usage và khả năng tái lập

ChatGPT hỗ trợ thiết kế prompt và review định hướng theo thông tin sinh viên cung cấp; Codex đọc/sửa repository và thực thi lệnh; Graphify định hướng quan hệ trước khi kiểm source. Không có transcript ChatGPT riêng để gán từng output; index Graphify cũ không thay thế real tests. [AI Usage Log](ai-usage-log.md) phân biệt vai trò, bằng chứng và giới hạn, không khẳng định có người kiểm thử độc lập.

Baseline `a2e0c070d694054001767979fe3f247e7ebff6be`; checkpoint tài liệu trước `687953784957242ed47390f0fb8652680fa726b8`. [Traceability](traceability.md) ghi SHAs chứa evidence; phiên bản báo cáo được định danh bằng commit chứa `report.md` trong lịch sử Git. Commit local không tự chứng minh remote đã cập nhật.

[README](README.md) tách core commands không phụ thuộc historical HEAD khỏi runners giới hạn HEAD/Windows; replay dùng scratch copy, không ghi đè evidence. [PR manifest](pr-staging-manifest.md) xác định source/tests/docs và evidence thiết yếu, cùng artifacts chỉ cần lưu trữ bổ sung. Không có execution mới để thay thế kết quả lịch sử.

## 8. Reflection — 328 từ

Đếm bằng tách khoảng trắng, không tính heading/ghi chú; nội dung trùng [reflection.md](reflection.md). Phần reflection có AI hỗ trợ diễn đạt.

Niềm tin vào Undo tăng khi kiểm thử đối chiếu cả phản hồi API lẫn tài liệu OpenSearch đã lưu. Khôi phục chính xác lịch sử có Unicode, null và tool messages thuyết phục hơn việc chỉ nhìn nút Undo hoạt động. Kiểm thử khởi động lại API giúp phân biệt persistence thật với cache trình duyệt.

RED rồi GREEN cung cấp dấu vết rằng kiểm thử phát hiện hành vi còn thiếu trước khi sửa. T-11 đã đạt ngay từ RED nên không bị ép thất bại. Việc giữ kết quả đó giúp tránh nhầm mọi thay đổi là một cải tiến và giữ oracle độc lập với implementation.

Mutation M-01 cho thấy nuốt exception vẫn sai ngay cả khi CAS ngăn ghi đè. Bốn assertion phát hiện HTTP 409 thay vì 503. Kết quả này chứng minh khả năng nhận diện lỗi contract cụ thể, không chứng minh mọi lỗi storage đều được phát hiện. Khôi phục đúng hash bảo đảm mutant không lọt vào bài nộp.

Coverage cao không bảo đảm tính đúng: fake có thể mô phỏng sai server, nhánh lỗi chưa chạy vẫn nguy hiểm, còn cùng một dòng có nhiều kết quả. Vì vậy cần kết hợp ma trận rủi ro, real integration và lặp concurrency bằng barrier, đồng thời công khai những nhánh chưa được kiểm chứng.

NFR hiệu năng không đạt ở cả ba kích thước lịch sử; một ReadError còn chưa rõ nguyên nhân. Giữ NOT MET đáng tin hơn thay ngưỡng hoặc loại mẫu chậm. Quyết định giữ production tránh tối ưu theo phỏng đoán khi chưa xác định bottleneck.

Rủi ro còn lại là phản hồi bị mất sau commit, failover và cấu hình môi trường khác. Kiểm thử giá trị nhất tiếp theo là chủ động làm mất phản hồi Undo sau persistence, rồi xác minh GET reconciliation và không tự gửi lại mutation. Đó là đề xuất tương lai, chưa thực hiện trong bài này.

## Phụ lục tham chiếu ngoài nội dung chính

[Traceability đầy đủ](traceability.md) · [AI usage log](ai-usage-log.md) · [RED](evidence/red/) · [GREEN](evidence/green/) · [Integration](evidence/integration/) · [Frontend](evidence/frontend/) · [Mutation](evidence/mutation/) · [Quality](evidence/quality/) · [Performance](evidence/performance/). Logs/JUnit/raw samples ở repository; không đưa nguyên văn vào PDF chính.
