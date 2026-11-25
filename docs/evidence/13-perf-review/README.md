# Evidence Task 13 — rà soát hiệu năng đường phát hiện bất thường

**Ngày đo:** 2026-11-25 · **Gốc so sánh:** `bbd160d` (`dev/nghiapb`, tree trùng `origin/main` 62023bf)

**Đo cái gì:** chi phí từng bước trong một chu kỳ worker, độ trễ thật từ log lỗi tới lúc cụm
`anomalous` hiện ra, và độ trễ của đoạn UI; mỗi mục có số trước/sau trên cùng môi trường.

**Thay đổi được đo:**

| Mã | Thay đổi | File |
|---|---|---|
| P1 | Gộp ghi cụm + history của cả chu kỳ thành **một** request bulk với một `refresh="wait_for"`, thay cho 2 lệnh `index` mỗi cụm | `clustering/src/storage.py` (`write_cycle`), `clustering/src/worker.py` |
| P3 | `read_logs` chỉ lấy 5 trường `_source` mà pipeline dùng | `clustering/src/storage.py` |
| P2 | Dashboard theo nhịp worker: poll `/clustering/health` 5 giây/lần, `last_processed_at` đổi thì refetch `/clusters` | `web/src/lib/api.ts`, `web/src/lib/queries.ts`, `web/src/pages/DashboardPage.tsx` |

## Môi trường

| Thành phần | Cấu hình |
|---|---|
| OpenSearch | 2.17.1, container `lae-perf-os`, `--cpus=2 --memory=2g`, heap `-Xms512m -Xmx512m`, single-node, `127.0.0.1:19200`, `refresh_interval` mặc định (1 giây) |
| Worker, ingestion, demo-app | code repo chạy trên host, Python 3.10.11 |
| Máy | Windows 11, i7-12700H (20 CPU logic), 39,7 GB RAM |
| Web | Node v24.11.0, vitest 5.0.3, jsdom + fake timers |
| Cấu hình phát hiện | `WINDOW_SECONDS=60`, `HISTORY_WINDOWS=30`, `INGESTION_LAG_SECONDS=10`, `ANOMALY_THRESHOLD=3.0`, `ML_AUGMENT_ENABLED=true` |

Dữ liệu log: bộ sinh `clustering/evaluation/generate_timeline.py` seed 98 (cùng bộ với
`load-tests/prefill_error_storm.py`), nạp đủ 31 cửa sổ baseline.

**Nhiễu đã biết:** trong lúc đo có 4 tiến trình Python của một dự án khác chạy trên cùng máy
(CPU tổng 9–24%). Nó làm `analyze_s` dao động 5,9–14,6 giây ở mức 100 log/giây **ở cả hai biến
thể**, nên các bảng dưới ghi min/median/max thay vì một giá trị. Phần `writes_s` — phần P1 thay
đổi — không bị ảnh hưởng: 7/7 lượt của code cũ đều ≥ 33 giây, 7/7 lượt của code mới đều ≤ 1 giây.

## P1 + P3 — chi phí một chu kỳ (`perf_harness.py`)

Mỗi ô là min / median / max, giây. `n` = số lượt, chạy xen kẽ trước–sau để nhiễu phân bố đều.
Số thô: [`harness-truoc-sau.jsonl`](harness-truoc-sau.jsonl).

| ERROR/giây | logs_read | cụm | code | n | read | analyze | **writes** | **cycle** | RSS sau read (MiB) |
|---|---|---|---|---|---|---|---|---|---|
| 10 | 18 600 | 29 | cũ | 3 | 0,34 / 0,38 / 0,39 | 0,62 / 0,62 / 0,69 | 28,93 / **28,99** / 29,07 | 29,9 / **30,0** / 30,1 | 180,3 / 180,6 / 180,8 |
| 10 | 18 600 | 29 | mới | 3 | 0,35 / 0,36 / 0,62 | 0,61 / 0,62 / 0,62 | 0,68 / **0,92** / 1,02 | 1,65 / **1,89** / 2,27 | 170,9 / 171,2 / 171,4 |
| 50 | 93 000 | 33 | cũ | 3 | 1,63 / 1,65 / 1,83 | 2,98 / 3,03 / 3,03 | 33,53 / **33,68** / 37,48 | 38,19 / **38,31** / 42,33 | 286,2 / 286,5 / 286,9 |
| 50 | 93 000 | 33 | mới | 3 | 1,49 / 1,52 / 1,54 | 2,90 / 2,98 / 3,00 | 0,85 / **0,89** / 0,95 | 5,32 / **5,38** / 5,42 | 242,9 / 243,1 / 243,3 |
| 100 | 186 000 | 33 | cũ | 7 | 3,04 / 3,33 / 4,07 | 6,00 / 6,10 / 11,69 | 33,22 / **58,35** / 62,18 | 43,16 / **67,48** / 75,40 | 419,0 / 419,5 / 420,5 |
| 100 | 186 000 | 33 | mới | 7 | 2,76 / 2,90 / 3,60 | 5,94 / 8,29 / 14,63 | 0,27 / **0,51** / 0,96 | 9,21 / **12,14** / 18,92 | 333,1 / 333,9 / 334,2 |

**Đọc bảng:**

- **P1:** phần ghi giảm từ 29,0 → 0,92 giây (10/giây), 33,7 → 0,89 (50/giây), 58,4 → 0,51
  (100/giây). Chu kỳ ở mức 100/giây đi từ **vượt ngân sách 60 giây** (median 67,5) xuống 12,1 giây.
  Nguyên nhân gốc không phải số round-trip mà là mỗi lệnh `index` chờ một nhịp refresh 1 giây:
  một bulk cũng chỉ chờ **một** nhịp.
- **P3:** RSS sau khi đọc giảm 9,4 / 43,4 / 85,6 MiB ở 10 / 50 / 100 log/giây; `read_s` giảm nhẹ
  (3,33 → 2,90 giây ở mức 100/giây). Số cụm và `logs_read` không đổi — cắt `_source` không đổi
  kết quả phát hiện.

Tái lập (từ gốc repo, OpenSearch đã chạy ở `127.0.0.1:19200`):

```powershell
$env:PYTHONPATH = (Get-Location).Path
python docs/evidence/13-perf-review/perf_harness.py seed  --prefix p100 --rate 100 --minutes 31 --end 2026-11-25T00:30:00Z
python docs/evidence/13-perf-review/perf_harness.py cycle --prefix p100 --end 2026-11-25T00:30:00Z --ml on --writes loop   # code cũ
python docs/evidence/13-perf-review/perf_harness.py cycle --prefix p100 --end 2026-11-25T00:30:00Z --ml on --writes cycle  # code mới
```

## P1 — độ trễ end-to-end thật

demo-app + ingestion + worker thật, nền 10 ERROR/giây gửi lẻ qua `/ingest` (9001 request, **toàn
bộ 202**, không có 429), rồi bắn K=8 lỗi cùng loại vào một giây cố định trong phút. Mốc dừng là
lúc cụm `anomalous` đọc được từ OpenSearch.

Số thô: [`e2e-truoc.jsonl`](e2e-truoc.jsonl) / [`e2e-sau.jsonl`](e2e-sau.jsonl),
log worker: [`e2e-truoc-worker.log`](e2e-truoc-worker.log) / [`e2e-sau-worker.log`](e2e-sau-worker.log).

| Lỗi bắn | Giây trong phút | Code cũ (giây) | Code mới (giây) | Giảm |
|---|---|---|---|---|
| `runtime`, demo-web | 30 | 90,68 | 41,71 | −48,97 |
| `timeout`, demo-mobile-api | 55 | 79,33 | 16,77 | −62,56 |
| `connection`, demo-web | 30 | 91,00 | 41,14 | −49,86 |

Cả 6 lượt đều tìm thấy đúng cụm, `status=anomalous`, `log_count=8`.

`cycle_seconds` trong 14–15 chu kỳ liên tiếp cùng mức tải:

| Code | min | max | Số chu kỳ vượt ngân sách 60 giây | Cửa sổ bị bỏ |
|---|---|---|---|---|
| cũ | 29,76 | 64,42 | 1 / 14 | 0 |
| mới | 1,07 | 2,03 | 0 / 15 | 0 |

Hai lượt chạy không bỏ cửa sổ nào (`window_to` liên tiếp cách đúng 60 giây), nhưng code cũ đã có
một chu kỳ 64,4 giây — hết biên an toàn. Code mới dùng 1,1–2,0 giây trên ngân sách 60 giây.

Tái lập:

```powershell
docs/evidence/13-perf-review/e2e_run.ps1 -Repo <gốc repo> -WorkerPath <gốc repo> -Prefix e2esau -OutDir <thư mục kết quả>
```

## P2 — đoạn UI

Vitest + fake timers, chạy `App` thật với fetch giả: đặt Dashboard ở từng mốc 700 ms trong một
chu kỳ 30 giây, đổi `last_processed_at` của `/clustering/health`, rồi đếm thời gian tới khi
`/clusters` được gọi lại. Độ phân giải 100 ms, 43 mẫu mỗi biến thể.

Số thô: [`ui-hop-truoc.json`](ui-hop-truoc.json) / [`ui-hop-sau.json`](ui-hop-sau.json).

| Code | min | median | max | mean |
|---|---|---|---|---|
| cũ (`refetchInterval` 30 giây) | 0,6 giây | 15,3 giây | 30,0 giây | 15,3 giây |
| mới (bám heartbeat 5 giây) | 0,1 giây | 2,5 giây | 5,0 giây | 2,5 giây |

Chi phí: thêm 12 GET `/clustering/health` mỗi phút cho mỗi tab đang mở Dashboard, và chỉ khi
auto-refresh đang bật. Route này public, `no-store`, chỉ đọc 1 document heartbeat. Giữ nguyên
`refetchInterval` 30 giây làm đường dự phòng khi heartbeat không đọc được.

Tái lập (file test nằm ngoài `web/` nên phải chép vào `web/src/` mới chạy — nó import `./App`):

```powershell
Copy-Item docs/evidence/13-perf-review/ui-hop.test.tsx web/src/
cd web; $env:UI_HOP_OUT = "<đường dẫn>/ui-hop.json"; npx vitest run src/ui-hop.test.tsx
Remove-Item web/src/ui-hop.test.tsx
```

## Tổng độ trễ log → UI

Ghép đoạn phát hiện (bảng e2e) với đoạn UI (bảng P2), cùng nền 10 ERROR/giây:

| Code | log → cụm anomalous | + đoạn UI (median) | Tổng |
|---|---|---|---|
| cũ | 79–91 giây | 15,3 giây | 94–106 giây |
| mới | 17–42 giây | 2,5 giây | 19–44 giây |

Hai đoạn đo riêng rồi cộng lại, không phải một phép đo liên tục.

## Test

| Bộ | Kết quả |
|---|---|
| `pytest clustering` | 130 passed (gốc 125; thêm 5 test cho `write_cycle` và `_source` của `read_logs`) |
| `pytest ingestion` | 36 passed |
| `pytest demo-app` | 53 passed |
| `pytest query-api` | 385 passed, 7 skipped, 1 failed |
| `pytest load-tests` | 38 passed, 4 failed |
| `web`: `npm run lint` | exit 0, không cảnh báo nào ở file được sửa |
| `web`: `npm run test` | 134 passed (gốc 133; thêm 1 test cho P2) |
| `web`: `npm run build` | exit 0 |

5 test failed là **lỗi môi trường có từ trước**, không liên quan thay đổi này — chạy đúng cùng
tập test trên code gốc cho kết quả giống hệt (5 failed / 1 passed):

- `load-tests/tests/test_run_worker_storm_sh.py` (4 test): `subprocess.run(["bash", ...])` trên
  máy Windows này gọi ra `bash.exe` của WSL (chưa cài distro) chứ không phải Git Bash, báo
  `execvpe(/bin/bash) failed`.
- `query-api/tests/test_admin_login.py::test_browser_preflight_allows_json_login`: bản
  `opentelemetry-instrumentation-fastapi` đã cài lệch với starlette, báo
  `'_IncludedRouter' object has no attribute 'path'`.

## Không đo được trong lần này

VM production không kết nối được lúc đo (TCP 443 tới `23.98.41.222` hết thời gian chờ,
2026-11-25T00:21Z), nên toàn bộ số ở đây là môi trường local. Phần chờ `wait_for` gắn với nhịp
refresh 1 giây của OpenSearch nên ít phụ thuộc phần cứng; phần `analyze` trên VM 2 vCPU dùng
chung có thể chậm hơn local. Độ trễ webhook → email cũng không nằm trong các số trên.

## File trong thư mục

| File | Nội dung |
|---|---|
| `perf_harness.py` | nạp log và đo từng bước một chu kỳ (`seed`, `cycle`) |
| `harness-truoc-sau.jsonl` | 26 lượt đo chu kỳ, trước và sau |
| `storm.py`, `e2e_probe.py`, `e2e_run.ps1` | nền error storm, bắn lỗi + chờ cụm, script chạy cả phiên |
| `e2e-truoc.jsonl`, `e2e-sau.jsonl` | 3 lượt e2e mỗi biến thể |
| `e2e-truoc-worker.log`, `e2e-sau-worker.log` | log worker trong lúc đo e2e |
| `e2e-truoc-storm.json`, `e2e-sau-storm.json` | số request storm đã gửi và mã trả về |
| `ui-hop.test.tsx` | đo độ trễ đoạn UI |
| `ui-hop-truoc.json`, `ui-hop-sau.json` | 43 mẫu mỗi biến thể |
