# VT-013 — Curated PR staging manifest

MSSV **23001904** · branch `feat/vt013-undo-manhpd` · HEAD trước checkpoint cuối `687953784957242ed47390f0fb8652680fa726b8`.

Manifest xác định allowlist checkpoint sáu tài liệu và phạm vi PR đề xuất; không chứng minh PR đã mở hoặc commit đã push. Baseline: `a2e0c070d694054001767979fe3f247e7ebff6be`. GitHub read-only trước checkpoint xác nhận main `33515bd50959155c579dcad26559f0aef69ff650`, merge base bằng baseline; assignment ahead 8/behind 18. Text probe ghi conflict `web/src/lib/api.ts`. Không merge hoặc sửa production. Bài tập cá nhân, không yêu cầu merge.

## 1. Phạm vi stage của lần sửa tài liệu hiện tại

Allowlist chỉ gồm sáu file:

```text
docs/assignments/VT-013/report.md
docs/assignments/VT-013/traceability.md
docs/assignments/VT-013/ai-usage-log.md
docs/assignments/VT-013/reflection.md
docs/assignments/VT-013/README.md
docs/assignments/VT-013/pr-staging-manifest.md
```

Sáu file trên tạo checkpoint tài liệu cuối, định danh bằng commit chứa phiên bản manifest này. Không stage source, tests, contracts, raw evidence hoặc các file untracked khác; PDF xuất sau checkpoint được review/commit riêng. Kiểm exact allowlist, `git diff --cached --check` và full staged diff; không dùng `git add .` hoặc add đệ quy cả evidence.

## 2. Source, contracts và tests thiết yếu của PR tổng thể

Các file này **đã commit**, không phải thay đổi mới của bước tài liệu. Giữ trong phạm vi feature khi chuẩn bị PR:

| Nhóm | Exact repository-relative paths | Lý do |
|---|---|---|
| Backend | `query-api/src/assistant/storage.py`; `query-api/src/assistant/router.py`; `query-api/Dockerfile` | Validation, snapshot, CAS/create-only, Undo, runtime schema |
| Contracts | `docs/architect/contracts/api-contract.md`; `docs/architect/contracts/assistant-conversation-schema.json` | Wire contract và legacy-compatible stored schema |
| Frontend | `web/src/lib/api.ts`; `web/src/lib/queries.ts`; `web/src/components/incident/AssistantPanel.tsx` | Authenticated Undo, revision, reconciliation, pending/accessibility |
| Backend tests | `query-api/tests/test_assistant.py`; `query-api/tests/test_assistant_storage.py`; `query-api/tests/test_assistant_undo_contract.py`; `query-api/tests/test_assistant_undo_backend.py`; `query-api/tests/test_assistant_undo_integration.py` | Regression, boundary/error/CAS contracts, real persistence |
| Backend test helpers | `query-api/tests/vt013_opensearch_fake.py`; `query-api/tests/vt013_integration_server.py` | Protocol-fidelity controls; deterministic AI với real API/OpenSearch |
| Frontend tests | `web/src/lib/assistant-undo.test.ts`; `web/src/components/incident/AssistantPanel.test.tsx`; `web/e2e/integration/assistant-undo.pw.ts`; `web/playwright.vt013.config.ts` | Consumer/UI/cache và browser persistence |
| Benchmark | `load-tests/vt013_undo.py` | Real 60-task workload; giữ guards và NOT MET |
| Assignment docs | `docs/assignments/VT-013/plan.md` và sáu file ở §1 | Approved AC/NFR, report, traceability, AI roles, reflection, reproducibility và manifest |

Không thay đổi source/tests/contracts trong quá trình curate tài liệu. [Traceability](traceability.md) xác định commit chứa từng nhóm evidence; SHA commit không đồng nghĩa đã push hoặc đã có CI mới.

## 3. Evidence thiết yếu cần giữ trong submission

Các đường dẫn dưới đây tương đối với `docs/assignments/VT-013/evidence/`. Dấu `*` là mẫu **inventory** trong đúng thư mục, không phải lệnh stage tùy ý. Giữ dữ liệu lỗi/setup/correction liên quan để không biến lịch sử thành chỉ có PASS.

| Phase | Artifact / mẫu thiết yếu | Giá trị bằng chứng |
|---|---|---|
| RED | `red/README.md`, `results.json`, `run_red.py`, `focused-red.log`, `focused-red.junit.xml`, `existing-tests.log`, `existing-tests.junit.xml`, `combined-regression.log`, `combined-regression.junit.xml`, `sandbox-probe.json`, `sandbox-probe.log` | 10 executed FAIL/4 PASS, 24 legacy PASS; tách sandbox blocker |
| GREEN | `green/README.md`, `test-results.md`, `results.json`, `run_green.py`; final `*.log`/`*.junit.xml`; `initial-results.json`, `backend-contracts-initial.log`, `backend-contracts-initial.junit.xml` | 14/24/52 và combined 90; giữ oracle/data correction |
| Integration | `integration/README.md`, `review.md`, `test-results.md`, `results.json`, `verification-summary.json`, `integrity.json`, `run_integration.py`, `Dockerfile.verify`, `reviewed-production.diff`; final host/Docker `*.junit.xml`, test/build/schema `*.log`, ownership/start/cleanup/image/version logs, `instance*.json` | Real 13 cases, Python 3.11 103, schema packaging, isolation |
| Real persisted state | `integration/host-artifacts/*.persisted.json`, `mapping-upgrade.json`, `not-found-shapes.json`, `processes.jsonl`; cùng mẫu trong `python311-artifacts/` | Exact history, SDK envelopes, mapping/CAS/restart/failure state |
| Initial integration failure | `integration/initial-attempt/results.json`, `real-opensearch.log`, `real-opensearch.junit.xml`, `backend-regression.log`, `backend-regression.junit.xml`, `test_assistant_undo_integration.py.snapshot`, `instance.json`, `opensearch-cleanup.log` | Harness URL error phải phân biệt production failure; đây là subset đã commit |
| Frontend | `frontend/README.md`, `test-results.md`, `run_frontend.py`, `run_e2e.py`, `red-results.json`, `red-targeted.log`, `red-targeted.junit.xml`, `session-race-red*`, `green-results.json`, `green-*.log`, `green-*.junit.xml`, `extra-checks.json`, `review-results.json`, `integrity.json`, typecheck/lint/build và discovery logs | 37 + 1 valid RED, 38/140 GREEN; diagnostics và opt-in E2E |
| Browser proof | `frontend/e2e.junit.xml`, `e2e-results.json`, `e2e-browser-proof.json`, `e2e-before.persisted.json`, `e2e-after.persisted.json`, E2E lifecycle/typecheck/Playwright logs và owned process record | Real browser/API/OpenSearch, không API interception; credentials không lưu |
| Mutation | `mutation/README.md`, `report.txt`, `results.json`, `run_mutation.py`, `mutation.diff`; baseline/mutant/restored/assignment-final logs và JUnit | 4 assertion kills; source hashes và worktree cleanup; không giữ mutant source làm production |
| Quality | `quality/README.md`, `final-summary.json`, `risk-matrix.json`, `results.json`, correction JSONs; `python-coverage.json`, `storage.cover.txt`, `router.cover.txt`, `frontend-coverage-summary.json`, `frontend-coverage/coverage-final.json`, `frontend-coverage/lcov.info`; coverage/order/races logs và JUnit | Statement/branch limits, P0 gaps, 400 fake-backed repetitions và shuffle |
| Quality tooling và browser repeats | `quality/python_coverage.py`, `run_quality.py`, `repeat_plugin.py`, `repeat_e2e.py`, `playwright.quality.config.ts`, `real-e2e-repetitions*.json`; `real-e2e-04/`…`real-e2e-13/` giữ final JUnit/results/raw proof/ownership records; setup-failure/correction logs | 10 actual scenarios PASS; preflight/config failures giữ riêng, không hidden retries |
| Performance | `performance/.gitattributes`, `README.md`, `results.json`, `summary.json`, `comparison.csv`, `review.json`, `samples.jsonl`, `summarize.py`, `regression-results.json`, backend-regression log/JUnit, environment/resource/process/ownership/start/cleanup records; `continuation/results.json`, `samples.jsonl`, `conversation-settings.json` và lifecycle/resource records | NOT MET, unresolved ReadError, raw p95/count/hash, real contention và môi trường |
| Checkpoint provenance | `checkpoint/README.md`, `checkpoint/manifest.json` | Selected-file hashes và phạm vi backend/integration checkpoint |

Mọi tên file ở một ô được hiểu nằm trong thư mục phase tương ứng, không phải repository root. Full logs không đưa vào report chính; dùng phụ lục repository. Các README/result đã commit là hồ sơ tại thời điểm phase, kể cả câu “chưa commit/chưa chạy phase sau”; không sửa lại raw/historical evidence để giống trạng thái hiện tại.

### Kiểm soát byte và dữ liệu

Giữ nguyên hai raw performance JSONL và recorded hashes. `.gitattributes` trong performance ngăn EOL conversion; raw terminal logs có thể chứa CRCRLF nên được lưu opaque. Không regenerate summary để che mojibake; dùng `continuation/results.json` UTF-8 cho payload. Thiếu cause/raw failed document của ReadError vẫn là gap. Không thay mẫu chậm, thresholds hoặc assertions.

Evidence là synthetic fixtures của disposable infrastructure. Trước staging sau này, kiểm actual content và pattern secrets mà không in giá trị nhạy cảm; endpoint 127.0.0.1, test IDs, process/container IDs và đường dẫn Windows là provenance, không phải thông tin portable. Pattern scan không chứng minh loại trừ mọi secret. Không đưa passwords, JWT, `.env` hoặc dữ liệu dự án thật vào PR.

## 4. Archive bổ sung và file không đưa mới vào PR

- **Không cần trong payload tối thiểu:** generated HTML/LCOV presentation assets khi JSON/LCOV gốc đã giữ; invalid initial coverage render; duplicate complete GREEN/E2E output và source snapshots không cần cho failure/correction audit. Ví dụ `quality/frontend-coverage/lcov-report/`, `quality/frontend-coverage-invalid-initial/`, `frontend/initial-e2e/` toàn bộ output lặp. Giữ trong archive phụ nếu cần bảo toàn hồ sơ; không loại log failure duy nhất đang được cite.
- **Không stage file local dư:** `*.api.log` rỗng, verbose `*events.jsonl` generation dumps, `integration/opensearch-server.log`, `performance/server-log.log`, `performance/continuation/server-log.log`, local diff audits và duplicate initial-attempt files chưa commit. Giữ raw latency `samples.jsonl` và actual result/JUnit; không áp dụng loại trừ mọi JSONL.
- **Ngoài bài tập:** `graphify-out/` và cache; `docs/chatgpt-context-vi.md`; `upgrade_assignment.md`; `upgrade_assignment_new.md`; `.env*`, credentials, real data, `.venv/`, `node_modules/`, `dist/`, caches, browser traces/video có khả năng ghi session. Không thêm chúng chỉ vì nằm trong worktree.

**Giới hạn quan trọng:** baseline→HEAD trước checkpoint tại `687953784957242ed47390f0fb8652680fa726b8` có 521 tracked changed files, bao gồm generated artifacts đã commit; thêm manifest làm phạm vi thành 522 files theo cùng base. Không stage lại không loại artifact cũ khỏi PR. Chỉ allowlist sáu tài liệu thuộc checkpoint này; không cleanup, rewrite history hoặc xóa evidence. Artifact được cite phải còn truy cập được, không bị loại bỏ chỉ để rút số file.

## 5. Kiểm tra đề nghị trước PR, chưa thực hiện stage

1. Xác minh branch/HEAD, index và diff với base main thực tế; không coi cached tracking ref là live remote.
2. Tách checkpoint sáu tài liệu ở §1 khỏi source/test/evidence và PDF xuất sau checkpoint. Review exact paths trước khi stage theo allowlist được duyệt.
3. Kiểm links và SHA từng artifact; giữ kết quả có lỗi, setup blockers, limitations và decision NOT MET.
4. So raw hashes và bảo đảm không mutant/secrets/real data; kiểm staged diff/check/stat. Không chạy test thêm để tạo execution claim cho bước tài liệu.
5. Commit checkpoint tài liệu chỉ theo chỉ dẫn được duyệt; PDF xuất sau đó cần kiểm và commit riêng. Push/PR cần chỉ dẫn riêng; tuyệt đối không merge nhánh assignment.
