<!--
SOURCE ONLY. Eight planned A4 page blocks, including references and reflection.
Target: A4, 16 mm margins, 10 pt body, 1.18 line spacing; no separate cover page.
Seven explicit page breaks define the page budget. No PDF was generated and the
rendered page count has not been verified. During the later authorized render,
verify <= 8 pages and adjust layout without omitting limitations or reflection.
-->
<style>
@page { size: A4; margin: 16mm; }
body { font-family: Arial, "Noto Sans", sans-serif; font-size: 10pt; line-height: 1.18; }
h1 { font-size: 16pt; margin: 0 0 8pt; }
h2 { font-size: 12pt; margin: 9pt 0 5pt; }
p, ul, ol { margin: 5pt 0; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; }
th, td { border: 1px solid #aaa; padding: 4pt; vertical-align: top; }
a, code { overflow-wrap: anywhere; }
.report-page-break { break-before: page; page-break-before: always; }
</style>

# 1. Project identification and requirements

**BT3 - AI-06 - VT-015: Reviewer authentication and cluster approval**  
Repository: **Log-Anomaly-Explorer**  
Published branch: [bt3/23001907-vt015](https://github.com/phamnghia57/Log-Anomaly-Explorer/tree/bt3/23001907-vt015)  
Verified published commit: `15bbd209de9a3e2b7f892d31798bd62924c63d72`

This academic source report summarizes verified repository evidence. It does not
claim a live deployment, production performance, or independent student authorship
of AI-assisted work. No screenshots or OpenSearch measurements are invented.

## Problem and acceptance criteria

An authenticated reviewer must inspect query/cluster data and approve an existing
cluster while preserving the original incident evidence. Admin access must remain
available, and Assistant must remain admin-only.

| Criterion | Observable outcome |
|---|---|
| Reviewer authentication and read access | Stored credentials issue a reviewer JWT; permitted GET routes succeed |
| Restricted writes | No original log/cluster/history mutation; Assistant denies reviewer access |
| Approval API | POST and GET `/clusters/{id}/approval` |
| Immutable approval identity | Actor from JWT and UTC timestamp from server; payload extras rejected |
| Atomic duplicate handling | Deterministic cluster ID; one 201 and one document; duplicates 409 |
| Absence/failure handling | Missing cluster 404; unavailable/unconfirmed storage 503 |
| Reproducible setup | Explicit reviewer/index initialization preserves existing accounts/data |

The implementation covers role-wide access, not per-tenant/per-cluster ACLs. Public
signup, revocation, account editing and cluster deletion are outside scope. Full
criterion-to-risk-to-test-to-file-to-evidence-to-commit mapping is in the
[traceability matrix](traceability-matrix.md).

**Publication:** only the named branch was pushed, without force or tags. GitHub's
default PR base is `main`. The local unrelated API contract edit was not staged
and does not occur in any VT-015 commit. The report/PR drafts are local review
artifacts and are not included in the published commit above.

<div class="report-page-break"></div>

# 2. Decision table and test design

The RED decision table contains 16 decision rows, expanded by pytest
parametrization into 22 contract cases. A condensed view follows; the complete
table and exact test names are preserved in [decision-table.md](decision-table.md).

| Identity / condition | Operation | Expected / risk addressed |
|---|---|---|
| Reviewer or admin, valid JWT | Four query/cluster/history GET routes | 200; preserve existing admin behavior |
| Reviewer or admin, existing cluster | Approve then read approval | 201 then 200; server identity/time; original evidence unchanged |
| Reviewer | Original-data mutation methods | 403 or 405; no original-data writes |
| Wrong-key or expired token | Approval POST | 401 before storage access |
| Already approved / competing reviewers | Repeated or simultaneous POST | 409 duplicate; one successful persistence write |
| Missing cluster | Approval POST | Actual lookup then 404; no orphan document |
| Approval storage failure | Approval POST | 503, no false successful response |
| Actor spoofing or original-data fields | Approval POST | 422, no write |

## Verification boundaries

The contract tests sign real PyJWT tokens and use the real FastAPI authentication
dependencies. They inject `app.state.approval_repository` with an atomic test
double. Its lock makes the double atomic; it cannot establish OpenSearch
atomicity. Original-data assertions check returned values and allowed repository
read calls, not database ACL enforcement.

Supplemental tests exercise the production repository client interface, reviewer
password login, Assistant denial, missing/unavailable storage and malformed token
inputs. Setup tests add real hashing, schema validation and login/JWT verification
over a stateful client double. The later workload connects the production
repository to SQLite transactions and sends actual HTTP requests to a separate
API process. These layers provide different evidence and are not interchangeable.

Reproduce the final suite from the repository root:

```powershell
./.venv-vt015/Scripts/python.exe -m pytest -q query-api/tests
```

The recorded final result is **298 passed**, with one existing Starlette/httpx
deprecation warning [E5]. Tests were not rerun just for preparing this source.

<div class="report-page-break"></div>

# 3. RED to GREEN and the implemented flow

| Stage | Actual recorded result | Interpretation |
|---|---|---|
| Existing baseline | 237 passed | Existing behavior before VT-015 [E1] |
| RED contract suite | 14 failed, 8 passed | Reviewer rejected and approval routes missing; no production change [E2] |
| GREEN contract suite | 22 passed | New contract behavior implemented [E3] |
| GREEN existing suite | 237 passed | Existing regression suite preserved |
| Focused auth/admin checks | 181 passed | Selected regressions plus supplemental tests; overlaps other suites |
| Coverage expansion | 274 passed | Ten additional focused tests |
| Explicit setup and final suite | 24 setup tests; 298 total passed | Provisioning gap addressed without changing RED expectations [E5] |

These counts are successive or overlapping test scopes, not additive independent
experiments. Full commands and logs are linked by the [evidence index](evidence-index.md).

## Vertical slice

`auth.py` validates credentials and uses the stored role. `tokens.py` issues and
validates JWTs. `require_reviewer` admits supported roles; `require_admin` protects
Assistant. `main.py` permits reviewer reads and adds approval POST/GET routes.

Approval POST validates the request and existing cluster, derives `approved_by`
from the JWT and `approved_at` on the server, then invokes
`ApprovalRepository.create`. The repository uses the separate `cluster-approvals`
index and OpenSearch `client.create(id=cluster_id)`. Creation yields 201, conflict
409, and storage failure 503. It never uses overwrite/upsert for approvals.

## Setup gap and safe initialization

Source review showed reviewer login was supported but only admin seeding existed;
approval-index initialization was also missing. The final setup command validates
environment credentials, initializes users/approvals indexes explicitly, then uses
create-only reviewer provisioning. Passwords are hashed with Argon2id. Existing
accounts, roles, passwords, mappings and original incident data are preserved.
The users schema now admits reviewer records. The command closes owned
connections and reports sanitized failures [E10].

Live OpenSearch setup was **not executed**. The 24 setup tests use a client double;
operators must validate actual index privileges and existing mappings.

<div class="report-page-break"></div>

# 4. Mutation, flaky tests and AI-assisted review

## Mutation experiment

On a temporary branch from GREEN, atomic create was deliberately replaced by
overwrite `index()` and acceptance of updated results. The relevant run produced
**1 failed, 26 passed** [E4]. The detector was
`test_repository_uses_separate_index_and_create_only`.

The observed failure was a mocked-client contract mismatch: the fixture configured
a successful create response, while the mutated index call returned an
unconfigured Mock and failed result confirmation. The explicit create-only
assertions were not reached in that run. All 22 RED API tests still passed because
they injected their own repository double. The mutation was killed, but this is
not evidence of detecting a real concurrent OpenSearch overwrite. The defective
implementation was removed and never merged into the submission branch.

## Two flaky-test risks investigated

**Scheduling:** the concurrent RED approval case passed 10/10 independent process
runs. Its barrier aligns request starts, not storage arrival; a ten-second barrier
timeout may fail on an overloaded runner. Its double remains the atomicity boundary.

**Shared state:** shuffled order initially produced 258 passes and six setup errors.
A two-test sequence reproduced deletion of Starlette application's
`assistant_conversations` state during supplemental fixture teardown. Replacing
attribute patching with a backing-mapping patch preserved the prior value. The
minimal sequence then passed and the shuffled suite passed all 264 historical
tests. Production code was not changed to compensate for the fixture [E6].

## AI review decisions

| Finding | Evidence and decision |
|---|---|
| Fixture teardown loses shared state | Supported by minimal failing/passing sequence. **Accept** and fix the test fixture; reject a production workaround |
| Production definitely fails because auto-create is disabled | Deployment settings were not collected. **Reject as established fact**; retain the provisioning concern and add explicit setup when authorized |
| Repository-level distributed concurrency remains unverified | RED double bypass and mutation output support the gap. **Accept** the limitation; SQLite later broadens local evidence but does not close it |

Codex assisted planning, RED tests, GREEN implementation, mutation, review,
verification and documentation under user direction. Human responsibility for
authorship, interpretation and academic submission remains explicit in the
[AI usage log](ai-usage-log.md).

<div class="report-page-break"></div>

# 5. Coverage measurements and residual gaps

Coverage was measured with pytest-cov 7.1.0 / coverage 7.17.1. The final recorded
run executed the complete **298-test** query-api suite and measured six production
modules [E5, E7]. Line and branch percentages are reported separately; they are
not the combined terminal “Cover” column.

| Module | Line coverage | Branch coverage |
|---|---:|---:|
| auth.py | 100.00% | 100.00% |
| approvals.py (including explicit index setup) | 100.00% | 100.00% |
| tokens.py | 97.14% | 100.00% |
| main.py | 95.59% | 85.71% |
| users.py | 93.94% | 87.50% |
| setup_reviewer.py | 97.22% | 87.50% |

## Remaining uncovered paths in the final source

- `main.py`: successful Assistant OpenSearch bootstrap (108-110), naive datetime
  normalization (152), history ValueError mapping (275-276), and arcs 106→108,
  151→152, 214→217, 270→273.
- `tokens.py`: defensive decoder-exception conversion at line 52; tested malformed
  expiry inputs are rejected before this fallback by the installed PyJWT.
- `users.py`: lines 65, 85, 107-108; arcs 64→65 and 84→85, including direct invalid
  username guards and connection-close error handling.
- `setup_reviewer.py`: direct module entrypoint line 49 / arc 48→49. Tests exercise
  the setup and CLI main functions, not that module-execution branch.
- `auth.py` and `approvals.py`: no missing measured lines or arcs.

Coverage identified useful gaps: missing-approval reads, unavailable repositories,
successful repository reads, unsupported issued roles and malformed expiry inputs
received focused tests. Setup added preservation, failure and account/index race
tests. No artificial production changes were made solely to raise a percentage.

Coverage is execution evidence, not proof of correctness, database ACLs,
distributed atomicity or production latency. The original four-module measurements
were preserved separately; they are not substituted for these final values.
Reproduction commands and environment preparation are in [README.md](README.md).

<div class="report-page-break"></div>

# 6. Concurrency and performance: simulated backend

**This experiment is SQLite-backed simulation, not real OpenSearch performance.**
Docker's CLI was present but its daemon was unavailable; local HTTP/HTTPS probes
to port 9200 were refused [E8]. An isolated temporary SQLite database used unique
key inserts through the actual production `ApprovalRepository`. Cluster reads
were fixtures. A separate single Uvicorn API process received loopback HTTP.

Hardware: Intel i5-6300U @ 2.40 GHz, two cores/four logical processors,
8,476,332,032 bytes RAM. Python 3.13.7; SQLite 3.50.4. The load generator and API
shared the host. Barriers released 2 or 80 client tasks. `perf_counter_ns` measured
complete HTTP response latency, including queueing but excluding barrier wait and
startup. Percentiles use nearest rank [E9].

| Scenario | Requests | 201 | 409 | Persisted | Errors |
|---|---:|---:|---:|---:|---:|
| Same cluster, 2 tasks | 2 | 1 | 1 | 1 | 0 |
| Same cluster, 80 tasks | 80 | 1 | 79 | 1 | 0 |
| 80 independent cluster IDs | 80 | 80 | 0 | 80 | 0 |
| Total | 162 | 82 | 80 | 82 | 0 |

Standalone 80-task response latency, seconds:

| Response group | n | p50 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|
| Independent-ID successes | 80 | 0.872 | 1.471 | 1.673 | 1.673 |
| Same-ID conflicts | 79 | 0.583 | 0.828 | 0.861 | 0.861 |
| Same-ID winner | 1 | 0.144 | 0.144 | 0.144 | 0.144 |

The measured p95 values are below **2.5 seconds locally**. The single winning
request has no useful percentile distribution. Only one batch per scenario was
recorded; an earlier run overlapping coverage is archived and excluded from this
standalone conclusion. Raw CSV and persisted documents were independently checked
against the response counts and percentile calculations [E9].

SQLite does not model OpenSearch transport, refresh waits, shards, replicas,
distributed failures or durability. These measurements establish neither a
production SLO nor actual OpenSearch concurrency correctness.

<div class="report-page-break"></div>

# 7. Personal reflection (Vietnamese draft)

The following 317-word body is reproduced from the existing reflection draft.
It is AI-assisted text for the student to verify and personalize before submission;
it does not claim independent authorship or unobserved deployment work.

Qua VT-015, tôi nhận ra rằng kiểm thử chức năng cần gắn với rủi ro cụ thể. Bảng quyết định giúp phân biệt quyền đọc, quyền phê duyệt và yêu cầu giữ nguyên dữ liệu gốc. Kết quả RED có 14 ca thất bại và 8 ca thành công cho thấy phần thiếu trước khi triển khai GREEN.

Bài học quan trọng với tôi là không diễn giải kết quả rộng hơn phạm vi kiểm thử. Đột biến thay thao tác tạo nguyên tử bằng ghi đè đã bị phát hiện, nhưng nguyên nhân là hợp đồng của client giả. Điều đó chưa chứng minh khả năng xử lý tranh chấp của OpenSearch thật. Việc ghi rõ giới hạn này làm báo cáo đáng tin cậy hơn.

Kiểm tra thứ tự chạy cũng cho thấy một vấn đề mà bộ kiểm thử thông thường bỏ sót: fixture làm mất trạng thái dùng chung. Chuỗi tái hiện ngắn và lần chạy xáo trộn sau sửa cung cấp bằng chứng rõ hơn việc chỉ chạy lại toàn bộ rồi thấy màu xanh. Tôi hiểu thêm rằng lỗi có thể nằm trong cách kiểm thử, không nhất thiết ở mã sản phẩm.

Tôi cũng thấy giá trị của việc tách tỷ lệ bao phủ khỏi kết luận về chất lượng. Các nhánh phân quyền và lưu trữ cần được kiểm tra bằng đầu vào có ý nghĩa. Kết quả tải SQLite qua HTTP giúp đánh giá cục bộ, nhưng không thay thế kiểm thử hệ thống phân tán.

AI hỗ trợ lập kế hoạch, viết mã, kiểm thử và tổng hợp tài liệu trong quá trình này. Trách nhiệm của người nộp vẫn là đọc lại thay đổi, đối chiếu nhật ký và trình bày trung thực. Trước khi coi tính năng sẵn sàng triển khai, tôi cần thêm bằng chứng trên OpenSearch và rà soát cấu hình vận hành.

<div class="report-page-break"></div>

# 8. Limitations, revisions and evidence references

## Limits and next review actions

Live OpenSearch provisioning, concurrency and end-to-end ingestion were not run.
Permissions are role-wide, without tenant/object ACLs or database credential
separation. Cluster existence lookup and approval create are not a cross-index
transaction; concurrent deletion remains untested. A timeout may persist a write
despite a 503. Setup preserves incompatible existing mappings and does not migrate
them. Retention, revocation, secret rotation and deployment policy need review.

The PR base is `main`; at publication it had 11 commits beyond the common ancestor,
while this branch had five. No merge/rebase or combined-base verification was
performed. Human approval is still required before PR creation. This Markdown
uses eight planned page blocks; the later authorized PDF render must confirm the
eight-page maximum. No final PDF has been generated.

## Verified revision ledger

| Stage | Commit |
|---|---|
| Baseline | `50a3af1a159253d9f4d414fb54a4a90b1c4eba4a` |
| RED | `a4f13a37942606572f98c70fe5df05bedd7d0868` |
| GREEN | `e0c5a4f2600e562bf0e465df300c178b912842d7` |
| Mutation review / fixture fix | `b627243c1f71a9417b581b2bc9e09a3f3a935a85` |
| Coverage / simulated workload | `0ae83dc5c70dab310fe78d6d31ff7aae66db2342` |
| Setup / submission package | `15bbd209de9a3e2b7f892d31798bd62924c63d72` |

## Evidence references

All references below resolve to files in the published submission commit. Detailed
reproduction, criteria mapping and AI provenance are provided in the README,
traceability matrix, AI usage log, reflection and evidence index alongside this
source. The report draft itself is a local review artifact.

- [E1] Baseline pytest log.
- [E2] RED pytest log and the separately linked decision table.
- [E3] GREEN VT-015 pytest log.
- [E4] Mutation command, output and detector limitation.
- [E5] Final 298-test command/output, including coverage.
- [E6] Post-mutation review and before/after flaky-test evidence.
- [E7] Final six-module coverage JSON, including missing arcs.
- [E8] Local OpenSearch availability probe.
- [E9] Workload summary; raw CSV and validation are linked in the evidence index.
- [E10] Explicit setup review and 24-test verification.

[E1]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/baseline-pytest.txt
[E2]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/red-pytest.txt
[E3]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/green-vt015-pytest.txt
[E4]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/mutation-pytest.txt
[E5]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/submission-pytest.txt
[E6]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/PATCH-mutation-review.md
[E7]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/submission-coverage.json
[E8]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/opensearch-probe.json
[E9]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/workload-summary.md
[E10]: https://github.com/phamnghia57/Log-Anomaly-Explorer/blob/15bbd209de9a3e2b7f892d31798bd62924c63d72/docs/task/VT-015/evidence/submission-setup-review.md
