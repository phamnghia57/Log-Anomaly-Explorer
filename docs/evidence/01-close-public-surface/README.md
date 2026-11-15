# Evidence Task 01 — đóng bề mặt public

**Đo cái gì:** cổng service nào gọi được từ Internet, và route nào của gateway trả gì khi không
đăng nhập.

| File | Đo ở đâu | Lúc nào | Trạng thái |
|---|---|---|---|
| `caddy-local.txt` | Máy dev, Caddy 2.8.4 trong Docker | 2026-11-15 | Đã có |
| `nmap-before.txt`, `curl-before.txt` | Máy **ngoài** VM, nhắm `23.98.41.222` | Trước khi deploy PR | Nghĩa điền |
| `nmap-after.txt`, `curl-after.txt` | Như trên | Sau khi deploy PR | Nghĩa điền |

Lệnh đo (chạy y hệt trước và sau):

```bash
nmap -Pn -p 9000-9002,16686 23.98.41.222
for p in /jaeger/ /demo/simulate-error /demo/health /ingestion/health /health /docs /openapi.json; do
  printf '%-22s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' https://23-98-41-222.sslip.io$p)"
done
```

**Kết luận local:** `/jaeger*` và `/demo/*` trả 401 khi thiếu/sai mật khẩu, kể cả khi chưa cấu
hình tài khoản; `/demo/health`, `/ingestion/health`, `/health` không bị chặn; `/docs`,
`/openapi.json` không còn tới query-api (rơi vào route mặc định của gateway). Cổng service trong
Compose chỉ bind `127.0.0.1`.

**Kết luận trên VM:** _(điền sau khi có nmap-after)_
