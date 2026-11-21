# Evidence Task 07 — worker clustering dưới error storm (issue #103)

**Đo cái gì:** `cycle_seconds` của clustering worker ở 10 / 50 / 100 log ERROR/giây, và từ mức nào
worker bắt đầu lỡ cửa sổ 60 giây.

Bảng kết quả và kết luận nằm ở
[`load-tests/README.md` mục Error storm](../../../load-tests/README.md#error-storm--worker-issue-103),
được sinh tự động từ các file trong thư mục này — không sửa tay.

## Cách tạo evidence

Trên VM, từ `~/prj2`, sau khi pause Healthchecks + UptimeRobot:

```bash
load-tests/run_worker_storm.sh run 10
load-tests/run_worker_storm.sh run 50
load-tests/run_worker_storm.sh run 100
load-tests/run_worker_storm.sh restore     # bat buoc, roi resume uptime check
load-tests/run_worker_storm.sh summary     # dien bang vao load-tests/README.md
```

Chi tiết từng bước và lý do (index riêng, collector trong compose network, mount `load-tests`,
số Locust user, rate limit lúc đo): xem `load-tests/README.md`.

## File cho mỗi mức `<R>` ∈ {10, 50, 100}

| File | Nguồn | Dùng để |
|---|---|---|
| `cycle-<R>.csv` | `capture_worker_cycles.py` (poll heartbeat 1 giây/lần) | `cycle_seconds`, `logs_read`, `clusters_out`, độ trễ `last_processed_at − window_to` |
| `worker-<R>.log` | `docker compose logs clustering --since <T0>` | đếm cửa sổ chính xác (không lỡ nhịp polling) |
| `storm-<R>_stats.csv`, `_failures.csv`, `_exceptions.csv` | Locust `--csv` | throughput thực, số 202 / 429 / lỗi khác |
| `locust-<R>.txt` | output Locust | bản đọc được của bảng trên |
| `docker-stats-<R>.txt` | `docker stats --no-stream` mỗi 5 giây | CPU / RAM từng container trong lúc đo |
| `prefill-<R>.json` | `prefill_error_storm.py` | đã nạp đủ 30 cửa sổ baseline chưa |
| `run-<R>.json` | `run_worker_storm.sh` | commit, vCPU, RAM, CPU model, heap OpenSearch, seed, số user, rate limit lúc đo |

Sau `summary`: `summary.md`, `summary.json`, và `issue-step2.md` **nếu** có chu kỳ > 30 giây
(thân issue cho bước 2 của #103).

## File hiện có trong thư mục

- `heartbeat-sau-deploy.json`, `worker-cycles-idle.txt`: heartbeat và log worker **lúc rảnh**
  (0 log/chu kỳ, `cycle_seconds` ~5 ms) ngay sau khi deploy PR #117 — chỉ chứng minh heartbeat có
  đủ trường mới, không phải số đo tải.
