PR #117 bổ sung lịch sử mới nhất, alert có link điều tra, giám sát worker và retention cho cluster-history. Hai lỗi review được sửa: đọc incident lỗi kho không còn làm dừng worker, và webhook lỗi ở một chu kỳ không còn tắt ping thành công ở mọi chu kỳ yên tĩnh tiếp theo.

## Phạm vi theo issue

| Issue | Thay đổi |
|---|---|
| #97 | `list_history` lấy N điểm mới nhất bằng sort giảm dần rồi đảo kết quả để trả về tăng dần; áp dụng chung Incident View và AI Assistant. |
| #98 | Replay seed 98 với cửa sổ 60s, 30 cửa sổ baseline; 32 tổ hợp ngưỡng/ML/similarity, metric và predictions được lưu. Chọn ngưỡng Compose 3.0, giữ ML bật và similarity 0.9. |
| #101 | Alert thêm `signature` và `incident_url`, URL-encode ID; bỏ gửi cho incident acknowledged; giữ ngưỡng và cooldown. Contract được bổ sung theo hướng tương thích consumer cũ. |
| #102 | Ping sau heartbeat; webhook lỗi phát `/fail` nhưng không phát success cùng chu kỳ. Chu kỳ tiếp theo thành công có thể ping success dù không có alert. Replay không ping; URL bí mật không được log. |
| #103 | Heartbeat ghi `cycle_seconds`, `logs_read`, `clusters_out`, `window_to`; mỗi record chỉ ghi cluster một lần. Có collector heartbeat và `ErrorStormUser` tái dùng generator 03a. Chưa có phép đo tải VM. |
| #109 | Worker chạy history retention tối đa một lần/giờ theo `RETENTION_DAYS`, giữ điểm tại cutoff; chặn index pattern, cập nhật contract và test. Phần quarantine/log rotation thuộc các thành viên khác. |

## Quyết định cần giữ

- Incident lookup **fail-open chỉ với `StorageError`**: ghi cảnh báo chung và tiếp tục xét gửi theo ngưỡng/cooldown. Không ghi exception có thể chứa secret. `RuntimeError` và lỗi lập trình khác vẫn được phát ra. Khi các thao tác khác thành công, worker tiếp tục ghi cluster, history và heartbeat.
- `delivery_failed` được reset đầu mỗi chu kỳ. Không ghi đè `/fail` bằng success ngay trong chu kỳ đó; chu kỳ sau không có alert vẫn ping success sau heartbeat. Success xác nhận chu kỳ worker hoàn tất, không bảo đảm webhook/email đã được sửa.
- `first_anomaly_after` **giữ `size: 1` và sort `asc`**: cần tìm lần tái phát ĐẦU TIÊN sau `resolved_at`, khác với yêu cầu lấy các điểm history mới nhất. Không đổi hàm này sang lấy lần tái phát cuối.
- Dùng tên env `ALERT_WEB_BASE_URL` cho URL frontend, thay cho tên dự kiến `PUBLIC_WEB_URL`. Không cấu hình thì `incident_url=null`.

## Ngưỡng và giới hạn chất lượng

Trên seed 98 synthetic, ML bật/similarity 0.9: ngưỡng 2.0 có precision 0.559, recall 0.9, 5.789 alert giả/giờ yên tĩnh và 34 alert; ngưỡng 3.0 có precision 1.0, recall 0.9, 0 alert giả/giờ và 17 alert. Trễ trung bình tăng từ 1.222 lên 1.556 cửa sổ. Vì vậy mặc định **Compose và `.env.example`** đổi 2.0 → 3.0; fallback Python không có env vẫn là 2.0. Kết quả một seed không chứng minh chất lượng production, vẫn bỏ sót 1/10 incident.

**Tắt ML phải đặt đồng thời `ANOMALY_THRESHOLD=1.5`**: rule-only ở 3.0 không có alert/không phát hiện incident; ở 1.5 có precision 1.0, recall 0.9, 0 alert giả/giờ và 54 alert. Đã ghi vào runbook, README và BENCHMARK.

## Kiểm chứng đã thực hiện

- `cd clustering && python -m pytest -q`: **125 passed** trên Python 3.13.7; xem `docs/evidence/pr117-review/pytest-clustering.txt`. CI Python 3.11 cần chạy lại sau khi đẩy bản sửa.
- Test hồi quy bao gồm incident storage lỗi vẫn gửi, lỗi lập trình không bị che, worker vẫn ghi cluster/history/heartbeat, webhook lỗi rồi 5 chu kỳ yên tĩnh vẫn ping, và webhook lỗi lặp lại không bị success ghi đè cùng chu kỳ.
- SHA-256 của ba asset 03b được đối chiếu với Git blob, 03a và generator CLI seed 98 chạy mới. Snapshot `96a8bf0` cho kết quả byte-identical, không tái hiện mismatch serialize trong review. Bảng hash và output: `clustering/evaluation/runs/20261118T083000Z_03b_seed98/README.md` và `asset-verification.txt`.
- Live storage: xem `docs/evidence/02-history-sort/verify-live-history.txt` và README tại đó. Kết quả local isolated không thay thế kiểm chứng UI/email/VM.

## Merge gates / evidence còn lại

- [ ] #97: ảnh Incident View trước/sau trên cùng cụm chạy thật >2 giờ, >100 điểm.
- [ ] #101: ảnh email trước/sau và bảng đếm thao tác thật từ email tới stack trace; không coi payload mock là email thật. Nhóm xác nhận contract bổ sung trước merge.
- [ ] #102: worker thật stop/start, email down/recovered, thời điểm và thử webhook sai trên môi trường được phép. Không dùng ping giả lập để tuyên bố đạt mốc thời gian email.
- [ ] #103: chạy 5 phút ở 10/50/100 ERROR/s, ghi throughput thực, baseline/warm-up, Docker stats và cycle CSV; kết luận lỡ cửa sổ. Chỉ tối ưu tiếp nếu số đo kích hoạt tiêu chí >30s.
- [ ] #109: số đo disk và `_cat/indices` trước/sau retention trên môi trường nghiệm thu; xác nhận phần quarantine/log rotation với người phụ trách.
- [ ] Chốt với Minh: `ErrorStormUser` đã có, ai chạy tải và điền bảng số đo; bản nháp thông báo tại `coordination-minh.md`.

Không coi các gate chưa đo là đã đạt chỉ vì unit test xanh. Khi còn thiếu evidence, giữ PR ở trạng thái chờ nghiệm thu hoặc thống nhất follow-up trước merge.

Closes #97
Closes #98
Closes #101
Closes #102
Closes #103
Closes #109
