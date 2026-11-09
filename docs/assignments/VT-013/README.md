# VT-013 — Hướng dẫn tái lập và hồ sơ nộp bài

**AI-06 — Log Anomaly Explorer · SE2026-T04 · MSSV 23001904**

HEAD trước checkpoint cuối: `687953784957242ed47390f0fb8652680fa726b8`. Sáu tài liệu đã được người dùng duyệt; phiên bản được xác định bằng commit chứa [PR staging manifest](pr-staging-manifest.md). Các commit evidence nằm trong [traceability](traceability.md). Checkpoint tài liệu không bao gồm PDF xuất sau đó; không có test execution mới hoặc tuyên bố checkpoint này đã push.

Undo một lượt Assistant Send đã hoàn tất, lưu một snapshot trong cùng document OpenSearch. **Kết quả chức năng có bằng chứng trong phạm vi kiểm thử; NFR 60 concurrent tasks / p95 ≤ 2.0s: NOT MET.** Người dùng đã chọn giữ nguyên production (Option A), không tối ưu hoặc A/B. Các lệnh dưới đây là hướng dẫn, **không được chạy lại trong bước viết tài liệu này**.

Send được chọn vì append ở mức nghiệp vụ được lưu bằng replacement toàn bộ document ở baseline, không có concurrency precondition. Hai request cùng đọc H rồi ghi H+A và H+B có thể cùng trả thành công nhưng mất A. Undo snapshot phục hồi lượt hoàn tất; CAS/create-only ngăn mất cập nhật mới hơn. Đây là rủi ro lost update đã được T-14 RED tái hiện, không phải một Delete API được giả định. [Baseline/spec](plan.md), [RED](evidence/red/README.md).

## Tài liệu và kiến trúc

- [Đặc tả gốc, đúng năm AC](plan.md), [truy vết requirement/test/SHA](traceability.md).
- [Báo cáo nguồn PDF](report.md), [AI usage log](ai-usage-log.md), [reflection](reflection.md).
- `AssistantPanel` → React Query hooks → authenticated API client → FastAPI Assistant router → `ConversationRepository` → OpenSearch. AI generation chỉ chạy trong Send.
- Backend: [router.py](../../../query-api/src/assistant/router.py), [storage.py](../../../query-api/src/assistant/storage.py). Public [API contract](../../architect/contracts/api-contract.md) và [stored schema](../../architect/contracts/assistant-conversation-schema.json).

Invariant: mutation chỉ commit trên đúng phiên bản đã đọc; messages và recovery snapshot được lưu nguyên tử. Existing write dùng `if_seq_no` + `if_primary_term`; absent write dùng create-only. Undo phục hồi nguyên mảng messages, giữ `created_at`, đổi revision/`updated_at`, tiêu thụ snapshot. Không redo, không rollback generation đang chạy.

| Endpoint (admin Bearer JWT) | Body | Thành công |
|---|---|---|
| `GET /assistant/clusters/{id}/conversation` | Không | 200, toàn bộ hội thoại |
| `POST /assistant/clusters/{id}/conversation/messages` | `{"message":"text"}` | 200, history mới + metadata |
| `POST /assistant/clusters/{id}/conversation/undo` | `{"expected_revision":"1:0"}` | 200, history restored, revision mới, Undo false |

Response: `{cluster_id, messages, revision, undo_available}`; revision null chỉ khi document chưa có. Persisted empty history có token thật. Token canonical ASCII `term:seq`, term ≥ 1, seq ≥ 0, mỗi số ≤ 9223372036854775807; client không tự tạo token. Send strict string 1–4000 code points, không whitespace-only, giữ nguyên accepted API text, extra fields bị cấm.

Lỗi: 401 auth; 404 cluster; 422 invalid body/token; 409 `revision_conflict` hoặc `nothing_to_undo`; 503 storage unavailable/corrupt; 502 generation. Missing document khác missing index. Timeout có thể xảy ra sau commit: GET reconcile, không tự retry Undo. Browser Stop chỉ hủy request phía client.

## Điều kiện chung và môi trường đã ghi

Chạy lệnh từ repository root trừ nơi có `Push-Location`. Cần Git, Python với `query-api/requirements-dev.txt`, Node/npm với `web/package-lock.json`, Docker đang chạy, image `opensearchproject/opensearch:2.17.1`, Chrome cho E2E. Fresh dependency setup là việc riêng; bước tài liệu này không cài gì. Không dùng `.env` chứa endpoint/data chung để chạy bài test.

Runtime đã ghi: host Windows, Python **3.14.6**, pytest 9.2.0, httpx 0.28.1, opensearch-py 3.2.0; Docker Python **3.11.18** cũng đã chạy 103 cases. Frontend dùng Node **25.8.2**, Vitest/V8 provider **5.0.3**, Chrome **156.0.8078.80**. Node 25 nằm ngoài engine range đã khai báo của Vitest; chưa có run Node LTS được ghi. Requirements Python có khoảng version mở nên fresh install không bảo đảm lặp đúng mọi version. Xem versions trong JSON từng phase.

### A. Core commands không khóa historical HEAD

Các command Python/Node sau không hardcode `D:\SE`, không khóa commit và dùng cùng CLI trên các hệ điều hành có dependencies phù hợp. Đây là **recipe tái lập**, không phải bằng chứng đã kiểm chứng cross-platform. Từ repository root, chọn `python` đúng virtualenv; cần environment `STORAGE_BACKEND=memory`, `OTEL_EXPORTER_OTLP_ENDPOINT=` (rỗng), `LANGFUSE_TRACING_ENABLED=false`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `VITE_JAEGER_URL=` (rỗng), và bỏ inherited `PYTEST_ADDOPTS`/Langfuse credentials. Thiết lập biến môi trường theo shell của máy chạy; PowerShell recipe riêng ở phần B.

```text
cd query-api
python -u -B -m pytest -vv --tb=short -rA --color=no -p no:cacheprovider tests/test_assistant_undo_contract.py tests/test_assistant_undo_backend.py tests/test_assistant.py tests/test_assistant_storage.py
cd ../web
node node_modules/vitest/vitest.mjs run src/lib/assistant-undo.test.ts src/components/incident/AssistantPanel.test.tsx
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc -b
node node_modules/oxlint/bin/oxlint
node node_modules/vite/bin/vite.js build
cd ..
```

Kỳ vọng theo evidence lịch sử là backend 90 PASS, frontend targeted 38/full 140 PASS, typecheck/lint/build exit 0. Dependencies, local `.env` và version vẫn ảnh hưởng kết quả; lưu exit code từng command. Core suite dùng fake OpenSearch/mock HTTP. Không áp dụng kết quả này cho integration thật hoặc NFR.

### B. Recipe PowerShell và runners lịch sử

Từ đây các block PowerShell là hướng dẫn môi trường Windows đã ghi, **không phải lệnh portable shell-neutral**. Các runners còn có output cố định/HEAD guards được liệt kê riêng ở phần C. Không chạy vào evidence gốc.

Đường dẫn interpreter lịch sử `D:\SE\LAE-issue-73\.venv\Scripts\python.exe` thuộc sibling worktree, không phải prerequisite của máy khác. PowerShell chọn interpreter đã chuẩn bị tại máy chạy:

```powershell
$VT013Python = (Get-Command python).Source
& $VT013Python --version
$env:STORAGE_BACKEND = 'memory'
$env:OTEL_EXPORTER_OTLP_ENDPOINT = ''
$env:LANGFUSE_TRACING_ENABLED = 'false'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
Remove-Item Env:LANGFUSE_PUBLIC_KEY -ErrorAction SilentlyContinue
Remove-Item Env:LANGFUSE_SECRET_KEY -ErrorAction SilentlyContinue
$VT013Output = Join-Path ([System.IO.Path]::GetTempPath()) ('vt013-replay-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $VT013Output | Out-Null
```

`Get-Command python` phải trỏ tới môi trường có dependencies; trên máy ghi evidence, Python mặc định thiếu chúng. Windows sandbox từng chặn TestClient socketpair: timeout trước assertion là **setup blocker**, không phải RED. Không khắc phục bằng sửa oracle.

### B1. Core commands dưới PowerShell

```powershell
Push-Location query-api
& $VT013Python -u -B -m pytest -vv --tb=short -rA --color=no -p no:cacheprovider -o faulthandler_timeout=20 --junitxml="$VT013Output/backend.xml" tests/test_assistant_undo_contract.py tests/test_assistant_undo_backend.py tests/test_assistant.py tests/test_assistant_storage.py
Pop-Location
Push-Location web
$env:VITE_JAEGER_URL = ''
node node_modules/vitest/vitest.mjs run src/lib/assistant-undo.test.ts src/components/incident/AssistantPanel.test.tsx
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc -b
npm.cmd run lint
npm.cmd run build
Pop-Location
```

Lưu `$LASTEXITCODE` ngay sau mỗi lệnh khi ghi evidence mới. Kết quả lịch sử: backend 90 PASS = 14 focused + 24 regression + 52 additional; frontend 38 targeted và 140 full = 38 mới + 102 cũ. Lint exit 0 với 9 warning có sẵn; build có bundle-size warning. Typecheck/build lặp cùng check không tạo thêm unique tests. Các test core dùng fake OpenSearch / mock HTTP; không phải bằng chứng persistence thật.

RED backend nằm ở `4487c1d93c77c117b1c18c0f611cd76152e3a011` (production còn baseline); chạy focused trên snapshot đó mới kỳ vọng 10 FAIL/4 PASS. Chạy code cuối không tái tạo RED. [RED runner/logs](evidence/red/) và [GREEN runner/logs](evidence/green/) có exact argv, cwd, exit codes. Runners có thể ghi đè logs theo tên: chỉ replay trong **bản sao dùng một lần**, giữ evidence submission nguyên vẹn.

### B2. Runners integration và E2E cần môi trường dùng một lần

Trong bản sao repository dùng để replay, với Docker/image/Chrome sẵn sàng:

```powershell
& $VT013Python -u -B docs/assignments/VT-013/evidence/integration/run_integration.py
& $VT013Python -u -B docs/assignments/VT-013/evidence/frontend/run_frontend.py green
& $VT013Python -u -B docs/assignments/VT-013/evidence/frontend/run_e2e.py
```

Integration runner tạo container có label và port loopback ngẫu nhiên, kiểm version/cluster identity, tạo index test riêng, chạy 13 cases, build Docker Query API từ root, probe schema ở runtime, chạy 103 cases trong Python 3.11 và 90 regression host. Test image cài pytest development; không thêm production dependency. Runner dọn đúng container sở hữu, không delete/reset index chung. Credentials admin/JWT sinh tạm và không lưu log. Data tmpfs: không suy ra độ bền sau node restart.

`pytest tests/test_assistant_undo_integration.py` trực tiếp thiếu `VT013_INTEGRATION_CONTEXT` hợp lệ sẽ skip; archived manifest trỏ tới container đã xóa, không được tái sử dụng. Chỉ PASS khi 13 cases thật đã thực thi. E2E runner tạo API/Vite/OpenSearch riêng, seed admin thực, browser login → Send → Undo → reload, kiểm raw `_source`/version ngoài browser. Không chỉ chạy Playwright với response intercept. Kỳ vọng lịch sử: 1 scenario PASS; config `web/playwright.vt013.config.ts`, spec `web/e2e/integration/assistant-undo.pw.ts`, retries 0. Không chạy default/auth E2E vào dữ liệu chung.

## C. Runners khóa HEAD và tooling lịch sử

| Runner | HEAD thực thi bị guard | Commit chứa tooling | Giới hạn |
|---|---|---|---|
| `evidence/mutation/run_mutation.py` | chính xác `a275c52300d40e92681692a0cc894a9946cb0084` | `bc735253920db6bc51d19f12b0fb3d92f210a8c2` | Detached mutation worktree; phải copy tooling vào scratch snapshot đúng HEAD |
| `evidence/quality/run_quality.py` | prefix `bc73525` | `d899b960ea898d841a54a3d091019603e3768337` | Windows/external coverage provider; orchestration lịch sử có corrections riêng |
| `load-tests/vt013_undo.py` | prefix `d899b96`, đúng assignment branch | `e7aa0b969c756d2c3d12dfa7116fbd4936498eaf` | PowerShell host probe, Docker, fixed output; không chạy ở HEAD cuối |

Integration/E2E ở B2 không có các HEAD guards trên, nhưng vẫn phụ thuộc Docker, Chrome, môi trường Python/Node và output layout. Các runner không phải bằng chứng một lệnh fresh-clone portable. Archived manifests trỏ tới container đã xóa không phải runtime context tái sử dụng.

Các lệnh lịch sử (chỉ chạy trong scratch copy ở đúng HEAD được guard):

```powershell
& $VT013Python -u -B docs/assignments/VT-013/evidence/mutation/run_mutation.py
& $VT013Python -u -B docs/assignments/VT-013/evidence/quality/run_quality.py
```

**Không phải hai lệnh chạy nguyên trạng ở HEAD cuối.** Mutation runner yêu cầu chính xác HEAD `a275c52300d40e92681692a0cc894a9946cb0084`; quality runner yêu cầu prefix `bc73525`. Muốn replay lịch sử: chuẩn bị clone/scratch riêng tại HEAD thực thi, chép runner/evidence tooling tương ứng từ commit chứa artifact (xem [traceability](traceability.md)), và dùng môi trường đã chuẩn bị. Không xóa guard trong submission hay chạy mutant trên nhánh bài nộp. Các runner tạo output tên cố định; không dùng thư mục chứa bằng chứng gốc làm chỗ thử.

Mutation M-01 đổi đúng generic read handler `raise StorageError(...)` thành `return None` trong detached worktree. Kỳ vọng lịch sử: baseline 90 PASS, mutant 86 PASS/4 FAIL bằng assertion status 409 thay 503, restored/final mỗi lần 90 PASS, source SHA-256 trở về `ddaaf6057906c6d7242b1ebcdc79ff43101606d127c31f56575504ea1b2240e2`, worktree removed. T-12 không kill mutation vì typed missing-index handler không bị đổi. [Mutation README](evidence/mutation/README.md) giải thích oracle và exact diff.

Chạy riêng repeated races trên code hiện tại, không cần full historical runner:

```powershell
$VT013Repo = (Get-Location).Path
$env:PYTHONPATH = Join-Path $VT013Repo 'docs/assignments/VT-013/evidence/quality'
Push-Location query-api
& $VT013Python -u -B -m pytest -v --tb=short -p no:cacheprovider -p repeat_plugin --junitxml="$VT013Output/races.xml" tests/test_assistant_undo_contract.py::test_t14_concurrent_sends_cannot_silently_overwrite tests/test_assistant_undo_backend.py::test_t15_t16_competing_undo_mutations_use_the_same_version
Pop-Location
Push-Location web
node node_modules/vitest/vitest.mjs run --sequence.shuffle --sequence.seed=13013
node node_modules/vitest/vitest.mjs run --sequence.shuffle --sequence.seed=13014
Pop-Location
```

Kỳ vọng ghi nhận: 400 fake-backed races (4 variants × 100), mỗi shuffle 140 PASS. Plugin dùng deterministic barriers và fresh fixture state; không thêm retry hay sleep cho race.

Python coverage: `& $VT013Python -u -B docs/assignments/VT-013/evidence/quality/python_coverage.py` trong scratch copy. Stdlib trace gồm worker threads, **statement-line approximation**, không branch coverage. V8 command đã thực thi (từ `web`, coverage provider đúng version phải có sẵn):

```powershell
node node_modules/vitest/vitest.mjs run --coverage.enabled --coverage.provider=v8 --coverage.reporter=json --coverage.reporter=text --coverage.reporter=lcov --coverage.reportsDirectory="$VT013Output/frontend-coverage" --coverage.include=src/lib/api.ts --coverage.include=src/lib/queries.ts --coverage.include=src/components/incident/AssistantPanel.tsx
```

Provider **không nằm trong package-lock**: lịch sử cài development tooling ngoài repo tại `D:\SE\vt013-quality-tools`, có junction vào ignored node_modules; fresh clone chưa có. Không dùng standalone temp Vitest CLI (đã gây dual-runtime matcher failures). Xem [quality README](evidence/quality/README.md) cho exact setup đã ghi. Không coi “NOT MEASURED” là 0% hoặc PASS.

Lặp browser lịch sử dùng `repeat_e2e.py`: 10 actual passes nằm ở `real-e2e-04`…`real-e2e-13`, sau 10 Docker preflight failures và 3 config failures trước collection. Replay mặc định ghi `real-e2e-01`…`10` và từ chối thư mục đã có. Chỉ ở scratch copy trống output, chạy `& $VT013Python -u -B docs/assignments/VT-013/evidence/quality/repeat_e2e.py`. Không dùng rerun để che failure; không tuyên bố run_quality.py nguyên trạng đã tự hoàn tất campaign lịch sử. [final-summary.json](evidence/quality/final-summary.json) tổng hợp những lần chạy sửa tooling riêng biệt.

## Benchmark performance — hướng dẫn lưu trữ, không yêu cầu chạy thêm

User đã quyết định dừng optimization/A/B. Harness [vt013_undo.py](../../../load-tests/vt013_undo.py) và [performance evidence](evidence/performance/) được commit sau review tại `e7aa0b969c756d2c3d12dfa7116fbd4936498eaf`. Command lịch sử từ root:

```powershell
& $VT013Python -u -B load-tests/vt013_undo.py
# Continuation lịch sử, không phải một workload mới được phê duyệt:
$env:VT013_PERF_OUTPUT = Join-Path (Get-Location).Path 'docs/assignments/VT-013/evidence/performance/continuation'
$env:VT013_PERF_SIZES = '2,100'
& $VT013Python -u -B load-tests/vt013_undo.py
```

Harness guard: đúng branch `feat/vt013-undo-manhpd`, HEAD prefix `d899b96`, tracked diff sạch, refuses overwrite samples. Replay lịch sử cần scratch snapshot đúng HEAD và trích harness/tooling từ commit `e7aa0b969c756d2c3d12dfa7116fbd4936498eaf`; không tự bỏ guard hoặc sửa raw evidence. `summarize.py` cũng **ghi lại** summary/comparison, nên không chạy vào dữ liệu submission nguyên gốc. Chỉ đọc summary hiện có nếu cần xem kết quả.

Protocol: 60 workers + coordinator barrier; client connection/keepalive 60; 5 warm-up + 50 measured rounds, histories 0/2/100, nội dung 1 KiB/non-null. Timing POST → response + JSON decode sau barrier; seed/login/Send rearm/raw verification ngoài timing. p95 nearest rank trên successful measured requests, lỗi và warm-up lưu riêng; 409 contention tách khỏi distribution. Mỗi lớp phải p95 ≤ 2000 ms **và** không unexpected error, state đúng.

Kết quả thực: H0 1139/1140, p95 2097.897 ms, 1 ReadError và dừng sớm; H2 3000/3000, 2077.965 ms; H100 3000/3000, 2602.975 ms. **NOT MET** cả ba. Initial exit 1; continuation exit 0 chỉ nghĩa hoàn tất, không SLO PASS. 7139 successful measured Undo khớp persistence; failed H0 chưa xác nhận restoration, thiếu exception cause/raw failed document. H0 throughput không có. Real Undo/Undo và Send/Undo mỗi cặp một 200/một 409, winner state đúng, chỉ một observed interleaving.

Môi trường benchmark: shared Windows host, 1 API worker/Python 3.14.6, OpenSearch single-node 512 MiB heap/2 GiB limit/tmpfs, refresh 1s, resource snapshots ngoài load; không profile. Không suy rộng thành capacity production hoặc kết luận bottleneck đã chứng minh.

**Encoding caveat đã kiểm tra:** phần contention Unicode trong derived `summary.json` bị mojibake; `continuation/results.json` đọc UTF-8 có đúng U+0111 và nội dung 1024 byte. `summarize.py` dùng default encoding khi đọc results; locale đã kiểm là cp1252. Dùng results UTF-8 gốc để đọc payload/state; số p95/count và raw SHA-256 đã được tính lại chỉ bằng đọc raw samples, vẫn khớp. Đây không phải benchmark hoặc execution do người khác thực hiện độc lập. Không sửa raw hoặc derived evidence ở bước tài liệu này. Nếu sau này sửa reporter phải review riêng và giữ bản lịch sử, không chạy ghi đè để che khác biệt.

## Evidence index và phạm vi PR

[RED](evidence/red/) · [GREEN](evidence/green/) · [integration](evidence/integration/) · [frontend](evidence/frontend/) · [mutation](evidence/mutation/) · [quality](evidence/quality/) · [performance](evidence/performance/).

Trước checkpoint cuối, local `git log` xác nhận tám commit sau baseline, gồm performance `e7aa0b969c756d2c3d12dfa7116fbd4936498eaf` và tài liệu `687953784957242ed47390f0fb8652680fa726b8`. Reflog ghi `update by push` tới checkpoint cũ; không chứng minh checkpoint cuối đã push. [Giới hạn bằng chứng push](ai-usage-log.md#kiểm-tra-commit-và-giới-hạn-của-phát-biểu-push). Kiểm tra GitHub read-only trước checkpoint xác nhận main `33515bd50959155c579dcad26559f0aef69ff650`, cùng merge base baseline; assignment ahead 8/behind 18. Text probe ghi conflict `web/src/lib/api.ts`; chưa kiểm thử kết hợp với main và không thực hiện merge.

PR dự kiến bài tập cá nhân, **không yêu cầu merge**; base `main`, compare `feat/vt013-undo-manhpd`, title `[BT3][VT-013] Undo Assistant Send - Contract Testing`. Trước checkpoint cuối, diff ba chấm có 521 files; thêm manifest làm phạm vi checkpoint thành 522 files theo cùng base. [Curated PR staging manifest](pr-staging-manifest.md) phân biệt file thiết yếu, archive bổ sung và file phải loại; chỉ allowlist sáu tài liệu được stage, chưa thực hiện cleanup evidence hoặc tạo PR.

Checkpoint performance giữ nguyên byte các artifact đã chọn. [Scoped Git attributes](evidence/performance/.gitattributes) ngăn EOL normalization làm sai recorded hashes; `.log` là raw capture, có thể chứa CRCRLF nên được lưu opaque. Raw latency samples, số đo và kết luận NOT MET không đổi. Log API rỗng, generation event dumps và verbose server logs vẫn để local, không đưa vào checkpoint.

Loại khỏi PR: `graphify-out/`, `docs/chatgpt-context-vi.md`, `upgrade_assignment*.md`, local env/node_modules/dist/cache, verbose OpenSearch server logs/empty API logs/event dumps/diff audits và duplicate initial-attempt diagnostics đã chủ động để untracked. Không xóa chúng. Các initial failures đã được chọn commit vẫn là audit evidence, không xóa chỉ để đẹp kết quả. Giữ raw benchmark/JUnit/summary cần thiết, review secrets và staging allowlist trước commit.

Giới hạn còn lại: uncovered P0 paths, supported-Node portability, failover/TLS, lost response sau commit, shared-admin/mixed old-new writers và live AI chưa đủ bằng chứng. Tại lần rà soát trước checkpoint, báo cáo giảm từ 2626 xuống 2462 từ tách khoảng trắng, gồm reflection 328 từ; thay đổi trạng thái checkpoint không đổi nội dung kỹ thuật. Ước lượng khoảng 6–8 trang A4 ở chữ 11pt, giãn dòng 1.15, lề 18–20 mm; các bảng/URL/chuỗi monospace dài và bảng bị ngắt trang có thể làm vượt giới hạn. Số trang cuối phải kiểm từ PDF thực sau export. Phụ lục chi tiết nằm ở repository, không chép toàn bộ vào report chính.

### Trạng thái tài liệu và giới hạn kiểm tra

Checkpoint cuối chỉ gồm sáu tài liệu được duyệt; SHA tra bằng `git log -1 -- docs/assignments/VT-013/README.md`. PDF được xuất sau checkpoint và cần kiểm riêng số trang, font, bảng và URL trước khi commit artifact. Kiểm tra link/SHA/hash không phải suite rerun hoặc human verification độc lập. Không khẳng định PR conflict-free, checkpoint đã push hoặc mọi loại secret được loại trừ từ pattern scan. Số trang PDF phải lấy từ artifact thực, không suy ra từ độ dài Markdown.
