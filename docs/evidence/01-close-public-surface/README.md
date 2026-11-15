# Evidence Task 01 — đóng bề mặt public

**Đo cái gì:** cổng service nào gọi được từ Internet, và route nào của gateway trả gì khi không
đăng nhập.

| File | Đo ở đâu | Lúc nào | Trạng thái |
|---|---|---|---|
| `config-before-after.txt` | Máy dev, Caddy 2.8.4 + Docker | 2026-11-15 | Đã có — **số liệu trước/sau** |
| `caddy-local.txt` | Máy dev | 2026-11-15 | Đã có — chi tiết lần đo đầu |
| `portscan-after.txt` | Máy **ngoài** VM → `23.98.41.222` | Sau deploy | Nghĩa điền |
| `nsg-probe.txt` | Máy ngoài VM, cổng 9009 tạm | Sau deploy | Nghĩa điền |
| `curl-after.txt` | Máy ngoài VM → `https://23-98-41-222.sslip.io` | Sau deploy | Nghĩa điền |
| `compose-ps-after.txt` | Trên VM | Sau deploy | Nghĩa điền |

## Lưu ý về số liệu "trước"

Không có `nmap-before.txt` đo từ Internet: bản vá đã được deploy lên VM (commit `adf51a7`)
**trước khi** kịp quét cổng từ máy ngoài, nên trạng thái cũ trên VM không còn để đo. Ghi lại đúng
như vậy thay vì dựng số liệu.

Phần "trước" được thay bằng đo thật trên **cùng hai file cấu hình của commit cũ `d58abfb`**, chạy
trên máy dev với Caddy 2.8.4 — xem `config-before-after.txt`. Nó chứng minh được hai điều quan
trọng nhất: compose cũ bind `0.0.0.0` + `[::]` cho cả 4 cổng, và Caddyfile cũ cho `/jaeger`,
`/demo/*`, `/docs` đi thẳng tới upstream mà không qua lớp auth nào.

Điều phần này **không** chứng minh được là các cổng đó có thật sự tới được từ Internet hay không —
Azure NSG có thể đã chặn sẵn. Đó là mục đích của `nsg-probe.txt`: mở một cổng rỗng chưa dùng
(9009) trên VM rồi thử từ máy ngoài. Thông được nghĩa là NSG không chặn cổng cao, tức là trước
Task 01 bốn cổng kia thật sự hở ra Internet.

## Lệnh đo

Xem `docs/task/runbook.md` mục "Truy cập Jaeger, fault injection và Swagger" cho cách truy cập
sau thay đổi. Lệnh thu evidence:

```powershell
# Tu may NGOAI VM (PowerShell). Luu y: dung curl.exe, vi "curl" trong PowerShell
# la alias cua Invoke-WebRequest va khong hieu co -s/-o/-w.
$ip = "23.98.41.222"
foreach ($p in 9000,9001,9002,16686,443,80) {
  $c = New-Object Net.Sockets.TcpClient
  try { if ($c.ConnectAsync($ip,$p).Wait(5000)) { $s = "OPEN" } else { $s = "filtered (timeout)" } }
  catch { $s = "closed (refused)" } finally { $c.Close() }
  "{0,-6} {1}" -f $p, $s
}

foreach ($p in "/jaeger/","/demo/simulate-error","/demo/health","/ingestion/health","/health","/docs","/openapi.json") {
  "{0,-24} {1}" -f $p, (curl.exe -s -o NUL -w "%{http_code}" --max-time 10 "https://23-98-41-222.sslip.io$p")
}
```

**Kết quả mong đợi:** `9000`, `9001`, `9002`, `16686` ở `closed` hoặc `filtered`, trong khi `443`
và `80` **phải** `OPEN` (đối chứng: nếu cả 443 cũng không thông thì mạng của máy đo đang chặn
outbound, kết quả không nói được gì về VM). `/jaeger/` và `/demo/simulate-error` trả 401; ba route
health trả 200; `/docs` trả 200 nhưng chỉ có text, không phải Swagger.

**Kết luận trên VM:** _(điền sau khi có portscan-after.txt)_
