# VT-014 — Idempotent ingest (BT3 cá nhân, Chu Huy Minh – 23001905)

**Change request:** người dùng gửi lại cùng một yêu cầu mà không tạo dữ liệu hoặc giao dịch trùng.
Nhánh: `bt3/23001905-vt014` · Baseline: `33515bd` (main, PR #59).

## Hành vi mới (`POST /ingest`, `POST /ingest/batch`)

| Header `Idempotency-Key` | Kết quả |
|---|---|
| Không gửi | Như cũ: mỗi request sinh `log_id` mới (tương thích ngược) |
| Hợp lệ, lần đầu | Xử lý bình thường (202/400), ghi nhớ response trong `IDEMPOTENCY_TTL_SECONDS` (mặc định 86400) |
| Cùng key + cùng payload | Trả **đúng** status + body lần đầu, header `Idempotent-Replayed: true`, **không ghi thêm** |
| Cùng key + payload khác (hoặc khác endpoint) | `409 {"reason": "idempotency_key_reused"}`, không ghi |
| Sai định dạng (ngoài 1..128 ký tự `[A-Za-z0-9._:-]`) | `400 {"reason": "invalid_idempotency_key"}`, không ghi |
| Lần đầu lỗi storage (503) | Không ghi nhớ → retry cùng key được xử lý lại, vẫn không trùng |

`log_id` khi có key = `uuid5(key, fingerprint(payload), index)` → kể cả khi mất cache (restart, hết TTL,
nhiều replica) OpenSearch vẫn ghi đè đúng `_id`, không sinh document thứ hai. `log-schema.json` và
`LOG_MAPPING` **không đổi**. Giới hạn: cache replay là của một process (như rate limiter).

```bash
curl -X POST localhost:8000/ingest -H "Content-Type: application/json" \
     -H "Idempotency-Key: order-7f3a-0001" -d '{"timestamp":"2026-11-10T08:00:00Z",
     "level":"ERROR","service":"demo-web","trace_id":"t1","span_id":"s1","message":"x"}'
```

## Chạy test

```bash
cd ingestion
pip install -r requirements-dev.txt
python -m pytest tests/test_ingest_core.py tests/test_idempotency.py tests/test_idempotency_api.py -v
python -m pytest            # toàn bộ module (CI chạy lệnh này)
```

`test_ingest_core.py` và `test_idempotency.py` không cần FastAPI/mạng/OpenSearch.
`test_idempotency_api.py` cần FastAPI + httpx (tự SKIP nếu thiếu).

| Mục | Lệnh (từ thư mục gốc repo) |
|---|---|
| Mutation “đổi mapping response field” (bản sao tạm, không sửa code thật) | `python ingestion/tests/mutation/run_mutations.py` |
| Line + branch coverage (không cần coverage.py) | `cd ingestion && python tests/tools/coverage_stdlib.py src/idempotency.py src/ingest_core.py -- tests/test_ingest_core.py tests/test_idempotency.py` |
| Coverage bằng pytest-cov (nếu có) | `cd ingestion && pytest --cov=src --cov-branch --cov-report=term-missing tests/test_idempotency.py` |
| Flaky check (thứ tự, TZ, lặp concurrency, chặn mạng) | `cd ingestion && python tests/tools/flaky_check.py --orders 10 --repeat 200` |
| Tải 150 tác vụ đồng thời, p95 ≤ 4.0 s (harness) | `python load-tests/idempotency_harness.py --users 150 --tasks 20` |
| Tải trên stack thật (Locust) | xem docstring `load-tests/locustfile_idempotency.py` |

Evidence (log chạy thật): [`../docs/bt3/VT-014/evidence/`](../docs/bt3/VT-014/evidence/).
