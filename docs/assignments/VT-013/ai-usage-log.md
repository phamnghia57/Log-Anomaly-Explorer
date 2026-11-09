# VT-013 — Nhật ký sử dụng AI

MSSV **23001904** · AI-06 / SE2026-T04 · 2026-11-09 (Asia/Saigon).

Đây là nhật ký **tổng hợp lại** từ yêu cầu trong chat, [đặc tả đã lưu](plan.md), mã nguồn và evidence. Không phải transcript đầy đủ; các mô tả prompt/output được diễn giải, không gán thời điểm, số token hoặc phiên bản model không có bằng chứng. Công cụ: **Codex** (phân tích, đề xuất, sửa code/test theo từng lần cho phép, chạy lệnh và tổng hợp); **Graphify** (đồ thị quan hệ để định hướng đọc source).

## Các yêu cầu chính, output và quyết định

| Giai đoạn / prompt được diễn giải | AI output có căn cứ | Review / quyết định được ghi nhận |
|---|---|---|
| Khảo sát repository bằng Graphify, tìm hành động có nguy cơ mất dữ liệu; giải thích contract trước sửa | Call path frontend → API → repository; đề xuất Undo completed Send và snapshot/CAS; [plan §1–2](plan.md) | Người dùng chọn latest completed Send, chỉ yêu cầu planning trước code. Không ghi nhận biểu quyết/team approval ngoài chat |
| Chốt đúng 5 AC và risk-based plan, chỉ tạo plan.md | [plan.md](plan.md), commit `29f06e9cff420d87bf255d516dc2982b20f399c2` | Người dùng sau đó chỉ định plan là approved specification và cho phép RED |
| Viết T-03/06/11/12/14 trước implementation, giữ production | [RED README](evidence/red/README.md): 10 assertion FAIL, 4 PASS, legacy 24 PASS | T-11 vốn đúng được giữ PASS; không cố tạo lỗi giả. Người dùng cho phép GREEN dựa trên kết quả này |
| Minimal backend; sau đó kiểm chứng trên OpenSearch thật | [GREEN](evidence/green/README.md): 90 PASS; [integration](evidence/integration/README.md): 13 real PASS, Docker 103 PASS, build/schema probe PASS | Người dùng yêu cầu checkpoint backend đã review. Commit artifact: `17ae52feae4e3f799f2249478ac2434ab869ceba` |
| Frontend test-first, action tối thiểu và real browser E2E | [Frontend](evidence/frontend/README.md): 37 RED + F-10 RED riêng; 38 targeted / 140 full GREEN, E2E PASS; lỗi cache logout được tái hiện rồi sửa | Người dùng yêu cầu commit và push frontend, message `feat(vt013): add assistant undo UI and E2E verification`; commit `a275c52300d40e92681692a0cc894a9946cb0084` |
| Thử mutant nuốt read exception trong worktree riêng, không thay oracle | [M-01](evidence/mutation/README.md): 4 assertion kill, hashes phục hồi, 90 PASS sau khôi phục | Người dùng yêu cầu commit riêng evidence mutation: `bc735253920db6bc51d19f12b0fb3d92f210a8c2` |
| Đo coverage, risk coverage, repeated races/order/E2E | [Quality](evidence/quality/README.md): coverage có giới hạn, 400 fake race PASS, 10 actual browser PASS; setup failures giữ riêng | Người dùng yêu cầu commit quality evidence đã review: `d899b960ea898d841a54a3d091019603e3768337` |
| Đo real 60-task performance; sau đó chỉ chẩn đoán, không optimize | [Performance](evidence/performance/README.md): cả 3 lớp NOT MET, một ReadError; AI khuyến nghị giữ kết quả, phân biệt hypothesis với causal evidence | Người dùng xác nhận **Option A: giữ nguyên production, NOT MET; không A/B**. Artifact sau review: `e7aa0b969c756d2c3d12dfa7116fbd4936498eaf` |
| Chuẩn bị submission, không chạy thêm test/commit/PDF | Năm tài liệu tổng hợp, truy vết SHA, lệnh tái lập và giới hạn | Dừng chờ review ở bước tạo tài liệu; không tự gán PASS cho lần tổng hợp này |
| Sau review: commit các file bài tập còn lại và push | Tách checkpoint performance và tài liệu; scoped Git attributes giữ byte raw evidence, không sửa số đo | Người dùng cho phép commit/push trong chat; không cho phép tối ưu, A/B hoặc mở PR |

## Những khuyến nghị AI đã được sửa hoặc thu hẹp

### AI-REV-01 — Không đồng nhất missing document với missing index

**Khẳng định ban đầu được ghi trong plan:** repository đã phân biệt conversation vắng (`None`) với lỗi đọc (`StorageError`). **Bằng chứng phản bác:** baseline `ConversationRepository.get()` dùng `ignore=[404]`, chỉ kiểm `found`; [plan §2](plan.md#ai-rev-01--missing-document-versus-missing-index) ghi source/probe. [T-12 RED](evidence/red/README.md) thực sự nhận None/HTTP 200 khi phải StorageError/503.

**Correction:** chỉ document absence là None; index/transport/corrupt metadata phải lỗi. Hiện tại [storage.py](../../../query-api/src/assistant/storage.py), `get()` dòng 113–128; T-12 GREEN và real I-07 xác nhận [404 shapes](evidence/integration/host-artifacts/not-found-shapes.json). Không tuyên bố mọi lỗi read từng sai: T-11 ordinary exception đã PASS ở RED.

### AI-REV-02 — Revision “opaque tối đa 128 ký tự” chưa đủ contract

**Đề xuất ban đầu được ghi trong plan:** opaque revision có giới hạn chiều dài và reject stale. **Vấn đề:** baseline bỏ seq/term khi đọc và write response khi lưu; cách này chưa định nghĩa token, create race hoặc mapping conflict/503. [Plan §2](plan.md#ai-rev-02--revision-contract-was-insufficiently-specified) ghi rõ sự thiếu chính xác.

**Correction:** canonical `primary_term:seq_no`, term ≥ 1, seq ≥ 0, cả hai ≤ signed-64-bit max; client vẫn coi token opaque. CAS hai tham số cho update; create-only khi absent. [storage.py](../../../query-api/src/assistant/storage.py) `parse_revision()` dòng 38, `_write()` dòng 130; T-08/09/10, real I-05/06 kiểm chứng. Không sử dụng timestamp hoặc fallback unconditional write.

### AI-REV-03 — “Tái sử dụng fake hiện có” cần giới hạn

Fake cũ không enforce conditional arguments và có alias dữ liệu; thêm assertions trên fake đó chưa chứng minh concurrency. [Plan §2](plan.md#ai-rev-03--reusing-tests-requires-replacing-their-persistence-model) ghi đề xuất/correction; [vt013_opensearch_fake.py](../../../query-api/tests/vt013_opensearch_fake.py) mô hình hóa metadata, copies, CAS/create-only. Ba control tests ở RED chứng minh fake **vẫn cho overwrite nếu caller không gửi precondition**. Real I-05/06 mới kiểm chứng server thực thi. Đây là thu hẹp ý nghĩa bằng chứng, không cáo buộc kế hoạch cũ bỏ toàn bộ real integration.

### AI-REV-04 — Sửa dữ liệu kiểm thử, không sửa production cho lỗi oracle

[GREEN README](evidence/green/README.md#diagnosed-failure-retained-for-review) giữ run 51 PASS/1 FAIL: AI chuẩn bị `history + turn(...)`, làm expected và input chia sẻ dictionary. Production đã copy đúng. Correction là `deepcopy(history)` trong dữ liệu test mới; equality assertion giữ nguyên. Không tính lỗi này là valid RED của production hay mutation kill.

### Giới hạn quyết định performance

AI đã nêu các lựa chọn giữ nguyên, đổi deployment benchmark hoặc tối ưu nhỏ **nếu** có bằng chứng bottleneck; A/B limiter chỉ là đề xuất chưa thực hiện. Người dùng hiện **không phê duyệt** tối ưu/A/B và chọn giữ NOT MET. `refresh="wait_for"`, refresh interval 1s, endpoint sync, default limiter/pool là quan sát code/cấu hình hoặc giả thuyết; chưa có stage profile chứng minh nguyên nhân. Không bịa một lần human rejection cho một patch chưa tồn tại.

## Graphify và tính độc lập của verification

[Plan](plan.md#actual-executed-evidence-and-limitations) ghi graph 172 indexed files khớp baseline, 1458 nodes/2885 edges, warning và query truncation. [Frontend README](evidence/frontend/README.md) ghi rõ index đã cũ so với implementation, chỉ dùng như bản đồ, mỗi kết luận kiểm lại source; CLI từng cập nhật untracked cache timestamp. Không rebuild graph ở bước tổng hợp này, không dùng stale graph làm bằng chứng execution, không đưa `graphify-out/` vào PR. Token accounting không có giá trị đáng tin; số 0 placeholder không phải đo usage.

Human approval được ghi ở đây chỉ là những chỉ dẫn có trong chat; không xác nhận người dùng đã đọc từng dòng, tự chạy test, được team đồng ý merge hoặc được giảng viên duyệt. Evidence thực thi là log/JUnit/raw data của các phase trước. Lần này chỉ đọc, kiểm tra tài liệu và Git; không rerun để thay thế lịch sử.
