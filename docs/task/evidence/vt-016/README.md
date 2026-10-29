# VT-016 — Bulk import (`POST /ingest/bulk`)

Change request cá nhân hoá VT-016 (BT3, Phạm Bình Nghĩa — 23001909): thêm chức năng import
dữ liệu hàng loạt vào `ingestion`; **một bản ghi lỗi không được làm mất các bản ghi hợp lệ
khác trong cùng batch**.

Nhánh: `feature/bulk-ingest-23001909`. Baseline commit (trước khi đổi gì):
`549e8d4aec50a74f37f0b0171a5d951c3e055349` (main).

## Chạy test

```bash
cd ingestion
pip install -r requirements-dev.txt     # them hypothesis, pytest-cov so voi truoc
pytest tests/ -v                        # toan bo, bao gom 7 test moi cho bulk import
pytest tests/test_bulk_ingest.py -v     # chi test bulk import
```

Coverage (line + branch):
```bash
pytest tests/ --cov=src --cov-branch --cov-report=term-missing
```

## Thử endpoint mới

```bash
STORAGE_BACKEND=memory uvicorn src.main:app --port 8000
curl -X POST http://localhost:8000/ingest/bulk -H "Content-Type: application/json" -d '{
  "logs": [
    {"timestamp":"2026-10-29T09:00:00Z","level":"ERROR","service":"demo-web","trace_id":"a","span_id":"b","message":"ok"},
    {"level":"ERROR"}
  ]
}'
```
→ `207`, `accepted: 1, quarantined: 1, failed: 0` — bản ghi lỗi (`{"level":"ERROR"}`, thiếu field)
không làm mất bản ghi hợp lệ đứng cạnh nó.

## Load test (200 đồng thời, mục tiêu p95 ≤ 5.0s)

```bash
STORAGE_BACKEND=memory RETENTION_INTERVAL_SECONDS=0 \
  uvicorn src.main:app --host 127.0.0.1 --port 8010 &
locust -f ../docs/task/evidence/vt-016/load_test_bulk.py --headless \
  --users 200 --spawn-rate 50 --run-time 1m \
  --csv ../docs/task/evidence/vt-016/04-load-test
```
Kết quả thật đã chạy: `04-load-test_stats.csv` / `04-load-test-console.txt` — **p95 = 33ms**,
0 lỗi/36733 request. **Giới hạn**: in-memory, 1 tiến trình, localhost — không đại diện cho chi
phí ghi/đọc OpenSearch thật dưới tranh chấp đồng thời; xem phần "Performance/risk experiment"
trong báo cáo PDF để biết kết luận được giới hạn đến đâu.

## Các file evidence trong thư mục này

| File | Nội dung |
|---|---|
| `01-red-phase-pytest.txt` | Test fail đúng lý do (404) trước khi có code — TDD red |
| `02-green-phase-pytest.txt` | 19/19 test pass sau khi implement — TDD green, không phá test cũ |
| `03-mutation-killed-pytest.txt` | Mutation "trả success dù persistence thất bại" bị 1 test bắt được (mutation đã bị xoá khỏi code, chỉ còn evidence) |
| `04-load-test*` | Harness + kết quả load test 200 đồng thời |
| `load_test_bulk.py` | Script Locust dùng để chạy load test trên |

## Lưu ý review trước khi merge

Không merge nhánh này vào `main` nếu nhóm (ít nhất 1 thành viên khác ngoài Nghĩa) chưa review
diff của `ingestion/src/main.py` và `docs/architect/contracts/api-contract.md`.
