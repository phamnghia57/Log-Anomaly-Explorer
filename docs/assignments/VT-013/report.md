# BT3 — VT-013: Undo Assistant Send và Contract Testing

**MSSV:** 23001904 · **Nhóm:** SE2026-T04 · **Dự án:** AI-06 — Log Anomaly Explorer

**Nhánh:** `feat/vt013-undo-manhpd` · **Ngày tổng hợp:** 2026-11-09 (Asia/Saigon)

**Kết luận:** Có bằng chứng chức năng cho Undo và bảo vệ phiên bản trong phạm vi đã kiểm thử. **NFR hiệu năng NOT MET.** Quyết định cuối của người dùng là Option A: giữ nguyên production; không tối ưu, không A/B. Đây là báo cáo bài tập cá nhân, không đề nghị merge.

Nguồn PDF chưa render. Mục tiêu tối đa **8 trang A4**: nội dung §§1–3 khoảng 2 trang, §§4–6 khoảng 3 trang, §§7–8 khoảng 1–2 trang; phụ lục là liên kết tới repository, không chép logs. Khi export dự kiến dùng chữ 11pt, giãn dòng khoảng 1.15, lề 18–20 mm; phải kiểm lại số trang thực tế. Chưa tạo PDF và chưa xác nhận page count.

## 1. Bài toán, phạm vi và đặc tả

Send bổ sung một lượt hội thoại nhưng baseline thay toàn bộ document mà không kiểm phiên bản. Hai Send cùng đọc history H có thể ghi H+A rồi H+B, làm mất A. Đồng thời người dùng không thể đảo lượt Send hoàn tất gần nhất. Thay đổi VT-013 thêm một snapshot bền qua restart API và conditional persistence; không thêm service, dependency production, multi-level history hoặc redo. Bằng chứng baseline và call path được ghi ở [plan §1](plan.md#1-specification-verified-contracts-and-invariants).

Rủi ro chính của đề: dữ liệu rỗng/giá trị biên vượt validation. Kỹ thuật bắt buộc: contract testing. Mutation bắt buộc: nuốt exception và trả dữ liệu mặc định. NFR: 60 tác vụ Undo được xác thực đồng thời, p95 ≤ 2.0 giây theo protocol đã duyệt; không dùng latency Azure Send để thay thế chỉ số này.

Năm AC giữ nguyên ý nghĩa từ [đặc tả](plan.md#acceptance-criteria--exactly-five):

| AC | Điều kiện chấp nhận được đo |
|---|---|
| AC-01 | Undo hiện hành khôi phục messages sâu bằng H, kể cả thứ tự/timestamps/null/tool fields; GET/restart API giữ restoration; snapshot một mức bị tiêu thụ; Undo đầu lưu [] với revision mới |
| AC-02 | Missing/null/non-string/empty/whitespace/over-4000 bị 422 trước generation/write; meaningful 1 và 4000 Unicode code points hợp lệ |
| AC-03 | Malformed revision 422; stale revision 409; rejection không đổi messages/snapshot/revision |
| AC-04 | Read/write/mapping failure là lỗi/503, không empty success; missing index là storage failure; definite pre-write failure giữ state; designated test kill swallowed-exception mutant |
| AC-05 | Mutation dựa cùng persisted version có tối đa một commit; loser 409; kiểm Send/Send, Undo/Undo, Send/Undo và first creation |

**Invariant quan trọng nhất:** mutation chỉ commit trên đúng phiên bản đã đọc; messages mới và snapshot phục hồi phải commit nguyên tử. Empty history hợp lệ không được đồng nhất với storage failure. Hệ thống chia sẻ hội thoại theo cluster giữa các authenticated admins; sender-only Undo không thuộc phạm vi.

## 2. Kiến trúc và contract thực hiện

Call path: `AssistantPanel` → `useSendAssistantMessage` / `useUndoAssistantSend` → API client có Bearer → Assistant router → `ConversationRepository` → OpenSearch. Send đọc history, chạy generation/tools rồi lưu. Undo không gọi AI/tool. Source chính: [router.py](../../../query-api/src/assistant/router.py), [storage.py](../../../query-api/src/assistant/storage.py), [queries.ts](../../../web/src/lib/queries.ts), [AssistantPanel.tsx](../../../web/src/components/incident/AssistantPanel.tsx).

| Endpoint / request | HTTP thành công / contract |
|---|---|
| GET `/assistant/clusters/{id}/conversation` | 200 `{cluster_id,messages,revision,undo_available}` |
| POST `.../conversation/messages`, `{"message":"text"}` | 200, toàn bộ history sau completed Send và revision server |
| POST `.../conversation/undo`, `{"expected_revision":"1:0"}` | 200, history restored, revision mới, `undo_available:false` |

Send dùng strict string, độ dài raw 1–4000, reject whitespace-only và extra fields; accepted API text không bị trim. Revision canonical ASCII `primary_term:seq_no`, term ≥ 1, seq ≥ 0, mỗi thành phần ≤ 9223372036854775807; client coi token opaque. Absence có revision null; persisted [] có revision thật. Snapshot không lộ trong response.

401: JWT thiếu/sai; 404: cluster không tồn tại; 422: validation; 409: `revision_conflict` hoặc `nothing_to_undo`; 503: persistence; 502: generation. Undo so revision trước snapshot availability. Timeout/lost response có thể xảy ra sau commit: GET reconcile, không khẳng định storage chắc chắn chưa đổi. [API contract](../../architect/contracts/api-contract.md), [stored schema](../../architect/contracts/assistant-conversation-schema.json).

Repository lưu metadata seq/term ngoài `_source`; `_write()` dùng create-only khi absence, hoặc `if_seq_no` và `if_primary_term` khi update, không unconditional fallback. Send lưu `H+T` và `undo.messages=H` cùng document. Undo lưu H, `undo=null`, giữ conversation `created_at`, đổi `updated_at` và revision. Legacy không snapshot vẫn đọc được; mapping strict được thêm field `undo` disabled-indexing, không recreate index. Dockerfile copy schema runtime. [Review/source references](evidence/integration/review.md#persistence-contract-and-invariant).

Frontend chỉ thay cache bằng response được server xác nhận, không đoán turn là hai messages, không optimistic deletion/client revision. Pending Send/Undo khóa hai action; 409/503/network dùng GET reconciliation, không tự retry mutation. Stop vẫn cancellation, không server-side Undo. [Frontend review](evidence/frontend/README.md#contracts-explained-before-implementation).

## 3. Quy trình test-first và review AI

Spec → RED → GREEN → real VERIFY → frontend → mutation → quality → performance. Mỗi phase được người dùng cho phép riêng. Đặc tả giải thích contract/invariant trước code; RED được chạy trên production chưa có Undo. Logs/JUnit thất bại, correction của tooling và restored hashes được giữ; không sửa oracle để phù hợp hiện trạng.

| Nhận định/đề xuất AI cần sửa | Căn cứ và quyết định review |
|---|---|
| Đã phân biệt document absence với read failure | Baseline blanket 404 suppression nhầm missing index thành None; T-12 RED phát hiện. Chỉ genuine document absence là None; lỗi index/transport thành StorageError/503. Real I-07 xác nhận envelope thật |
| Opaque revision ≤128 ký tự là đủ | Chưa định nghĩa seq zero, numeric bounds, metadata và create race. Chốt canonical term:seq, CAS/create-only, ConflictError → 409; T-08/09/10 và I-05/06 kiểm chứng |
| Chỉ mở rộng fake cũ | Fake cũ bỏ qua CAS arguments và alias dữ liệu; sửa mô hình transport có control tests, sau đó real integration làm authority cho persistence |

Chi tiết đề xuất gốc, source và hệ quả ở [plan §2](plan.md#2-review-and-corrections-to-the-previous-ai-proposal) và [AI usage log](ai-usage-log.md). Một lỗi alias trong dữ liệu test GREEN mới được sửa bằng deepcopy; không đổi production đúng để chiều oracle sai. Cache logout race F-10 được viết RED trước correction, chứng minh cần check session ngay trước cache write. [GREEN diagnostic](evidence/green/README.md#diagnosed-failure-retained-for-review), [frontend diagnostic](evidence/frontend/README.md#diagnosed-failures-and-corrections).

## 4. Kết quả kiểm chứng chức năng và mutation

Các số sau là **execution lịch sử đã đối chiếu artifact**, không chạy mới khi viết báo cáo. Không cộng các rerun thành unique cases; full traceability gồm commit SHA tại [traceability.md](traceability.md).

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

M-01 thay đúng generic read exception handler từ raise StorageError thành return None trong detached worktree. T-11, T-22 và hai metadata cases nhận **409 thay 503**, kill mutant bằng assertion hiện có. CAS vẫn chặn create đè document: không tuyên bố history thực tế đã bị overwrite hoặc mutant trả 200. Ba T-12 vẫn PASS vì typed missing-index handler không đổi. Source phục hồi SHA-256 `ddaaf6057906c6d7242b1ebcdc79ff43101606d127c31f56575504ea1b2240e2`; temp worktree removed, không mutant trong submission. [Diff](evidence/mutation/mutation.diff), [results](evidence/mutation/results.json).

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

Không thấy application flake trong sampling đã chạy; không chứng minh zero flakiness. P0 coverage gate **chưa đầy đủ**: malformed/identity/pre-write schema, configuration và generation-error paths, Send/logout/401 còn gaps. TLS/security plugin, node failover, lost response sau commit, supported Node LTS, cross-browser và live Azure chưa đủ evidence. [Risk matrix](evidence/quality/risk-matrix.json). Real mixed Send/Undo một interleaving đã được bổ sung trong performance, chưa bao phủ mọi winner/failure ordering.

## 6. Performance: NFR NOT MET và quyết định kỹ thuật

Protocol duyệt: 60 authenticated workers, barrier gồm coordinator, histories 0/2/100, 1 KiB/non-null message, 5 warm-up + 50 measured rounds/lớp. Seed/login/Send rearm/raw GET validation ngoài timing; timer sau barrier bao gồm POST, response và decode JSON. p95 nearest rank trên từng successful measured request, không average round p95; errors/warm-up retained riêng; contention 409 không trộn vào latency success. [Protocol và raw evidence](evidence/performance/README.md).

| History | Successful / measured | p95 (ms) | Lỗi | SLO |
|---|---|---|---|---|
| 0 | 1139/1140; chưa đủ 3000 | 2097.897 | 1 ReadError, restoration chưa xác nhận | **NOT MET** |
| 2 | 3000/3000 | 2077.965 | 0 | **NOT MET** |
| 100 | 3000/3000 | 2602.975 | 0 | **NOT MET** |

Nguồn: [summary.json](evidence/performance/summary.json), [comparison.csv](evidence/performance/comparison.csv), [initial raw](evidence/performance/samples.jsonl), [continuation raw](evidence/performance/continuation/samples.jsonl). Tổng 7140 measured attempts, 7139 success và 900 warm-up riêng. Mọi successful measured Undo khớp persistence. Initial run dừng ở ReadError (exit 1); H0 throughput/cause text/raw failed document không được lưu, không suy đoán data loss. Continuation trên instance mới chỉ chạy H2/H100 (exit 0 là completion, không compliance). Không retry H0 để thay kết quả xấu.

Review tài liệu phát hiện mojibake trong chuỗi contention của summary dẫn xuất; [continuation results UTF-8 gốc](evidence/performance/continuation/results.json) giữ đúng Unicode/1024 byte. Reporter đọc theo default encoding, locale hiện tại cp1252. Recompute raw p95/hashes vẫn khớp; không sửa evidence. Dùng results gốc cho nội dung, giữ gap trình bày này công khai.

Real contention riêng Undo/Undo và Send/Undo mỗi cặp một 200/một 409, persisted winner đúng; Undo thắng cả hai observed pairs. Backend 90/90 PASS sau measurement. [Summary](evidence/performance/summary.json), [regression JUnit](evidence/performance/backend-regression.junit.xml).

Môi trường đo: Windows shared host, Python 3.14.6, một Uvicorn worker, OpenSearch 2.17.1 single-node/one-shard, heap 512 MiB, container 2 GiB, tmpfs, refresh interval 1s. Resource snapshots ngoài timed rounds, không profile hay peak sampling. H100 response khoảng 109 kB; workloads compressible. Source `refresh="wait_for"`, sync execution và thread/pool defaults gợi ý refresh wait/queue/serialization, **chưa chứng minh bottleneck**. [Settings](evidence/performance/continuation/conversation-settings.json), [environment/limits](evidence/performance/README.md#isolation-environment-and-resources).

**Review cuối:** A giữ nguyên bảo đảm dữ liệu và báo cáo NFR fail; B chỉnh deployment benchmark có thể đổi queue nhưng chưa chứng minh và mở thêm work; C production optimization chưa có causal evidence, có regression/scope risk. Người dùng chọn **A**, không B/C/A-B. Không đổi threshold, CAS, durability, validation hoặc error propagation để đạt điểm số đẹp. NFR chưa đạt không bị diễn giải thành feature đáp ứng đầy đủ mọi yêu cầu.

## 7. AI usage, tái lập và trạng thái nộp

Codex hỗ trợ khảo sát, spec, test-first implementation và evidence; Graphify hỗ trợ định hướng quan hệ. Index Graphify baseline cũ không thay thế source hoặc real tests; token usage không đo được. Các corrections cụ thể ở §3 và [AI Usage Log](ai-usage-log.md); không gán cho người dùng review chưa có trong chat. Reflection dưới đây là draft AI-assisted cần sinh viên xác nhận.

Baseline `a2e0c070d694054001767979fe3f247e7ebff6be`; HEAD tổng hợp ban đầu `d899b960ea898d841a54a3d091019603e3768337`. Evidence commits: plan `29f06e9cff420d87bf255d516dc2982b20f399c2`; RED `4487c1d93c77c117b1c18c0f611cd76152e3a011`; backend/integration `17ae52feae4e3f799f2249478ac2434ab869ceba`; frontend `a275c52300d40e92681692a0cc894a9946cb0084`; mutation `bc735253920db6bc51d19f12b0fb3d92f210a8c2`; quality `d899b960ea898d841a54a3d091019603e3768337`. Sau review, performance/harness được commit tại `e7aa0b969c756d2c3d12dfa7116fbd4936498eaf`, giữ nguyên bytes và raw hashes. SHA checkpoint tài liệu lấy từ `git log -1 -- docs/assignments/VT-013/report.md`.

[README tái lập](README.md) có core commands, real-integration lifecycle, E2E, mutation/quality guards và performance protocol. Một số runner hardcode historical HEAD, Windows paths hoặc output names, nên chưa phải một lệnh portable trên fresh clone. Chỉ replay trong scratch copy; không ghi đè raw evidence submission. Bước tổng hợp chỉ kiểm tài liệu/Git/artifact, không chạy lại suites để tạo PASS mới. Sau review, người dùng cho phép commit/push các file bài tập; chưa mở PR. PR dự kiến bài tập cá nhân, base main, compare nhánh assignment, không yêu cầu merge. Remote main chưa fetch nên PR diff phải review sau.

## 8. Reflection — 328 từ

Đếm bằng tách khoảng trắng, không tính heading/ghi chú; trùng [reflection.md](reflection.md). Bản nháp cần sinh viên xác nhận trải nghiệm và cách diễn đạt trước khi nộp.

Niềm tin vào Undo tăng khi kiểm thử đối chiếu cả phản hồi API lẫn tài liệu OpenSearch đã lưu. Khôi phục chính xác lịch sử có Unicode, null và tool messages thuyết phục hơn việc chỉ nhìn nút Undo hoạt động. Kiểm thử khởi động lại API giúp phân biệt persistence thật với cache trình duyệt.

RED rồi GREEN cung cấp dấu vết rằng kiểm thử phát hiện hành vi còn thiếu trước khi sửa. T-11 đã đạt ngay từ RED nên không bị ép thất bại. Việc giữ kết quả đó giúp tránh nhầm mọi thay đổi là một cải tiến và giữ oracle độc lập với implementation.

Mutation M-01 cho thấy nuốt exception vẫn sai ngay cả khi CAS ngăn ghi đè. Bốn assertion phát hiện HTTP 409 thay vì 503. Kết quả này chứng minh khả năng nhận diện lỗi contract cụ thể, không chứng minh mọi lỗi storage đều được phát hiện. Khôi phục đúng hash bảo đảm mutant không lọt vào bài nộp.

Coverage cao không bảo đảm tính đúng: fake có thể mô phỏng sai server, nhánh lỗi chưa chạy vẫn nguy hiểm, còn cùng một dòng có nhiều kết quả. Vì vậy cần kết hợp ma trận rủi ro, real integration và lặp concurrency bằng barrier, đồng thời công khai những nhánh chưa được kiểm chứng.

NFR hiệu năng không đạt ở cả ba kích thước lịch sử; một ReadError còn chưa rõ nguyên nhân. Giữ NOT MET đáng tin hơn thay ngưỡng hoặc loại mẫu chậm. Quyết định giữ production tránh tối ưu theo phỏng đoán khi chưa xác định bottleneck.

Rủi ro còn lại là phản hồi bị mất sau commit, failover và cấu hình môi trường khác. Kiểm thử giá trị nhất tiếp theo là chủ động làm mất phản hồi Undo sau persistence, rồi xác minh GET reconciliation và không tự gửi lại mutation. Đó là đề xuất tương lai, chưa thực hiện trong bài này.

## Phụ lục tham chiếu ngoài nội dung chính

[Traceability đầy đủ](traceability.md) · [AI usage log](ai-usage-log.md) · [RED](evidence/red/) · [GREEN](evidence/green/) · [Integration](evidence/integration/) · [Frontend](evidence/frontend/) · [Mutation](evidence/mutation/) · [Quality](evidence/quality/) · [Performance](evidence/performance/). Logs/JUnit/raw samples ở repository; không đưa nguyên văn vào PDF chính.
