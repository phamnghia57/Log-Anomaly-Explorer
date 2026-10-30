# JWT admin: triển khai và xác minh

Phạm vi của Mạnh: Query API/web dùng JWT admin, users ở OpenSearch hiện có. Không có
database/container mới, public signup, tự seed khi startup hoặc thay đổi frozen contracts.
Đọc thêm [Query API](../../query-api/README.md), [web](../../web/README.md).

## Cấu hình

- `JWT_SECRET`: backend bắt buộc khi login/verify JWT, ngẫu nhiên ít nhất 32 bytes UTF-8.
  Không có fallback; thiếu/yếu thì auth trả 503, không bypass. Giữ cùng secret cho các
  replica/restart trong secret manager; không đưa vào `VITE_*`, command arguments hay log.
- `JWT_EXPIRY_SECONDS`: số nguyên dương, mặc định `3600`. API ký HS256 với allowlist cố định,
  yêu cầu `sub`, `role="admin"`, `exp`. `expires_at` bằng thời điểm `exp`, không có leeway.
- `ADMIN_SEED_USERNAME`, `ADMIN_SEED_PASSWORD`: chỉ cần cho one-off seeding. Nạp từ secret
  manager hoặc prompt trong terminal, bỏ khỏi môi trường/container runtime sau seed.
- `USERS_INDEX`: mặc định `users`, cùng OpenSearch với logs/clusters; document ID là username.
- `OPENSEARCH_URL` và các `OPENSEARCH_*` hiện có: Python chạy trực tiếp đọc environment,
  không tự nạp `.env`. Compose mặc định dùng OpenSearch nội bộ, không publish 9200.
  Stack mặc định tắt OpenSearch security, nên phải giữ mạng nội bộ kín. Với remote cluster
  có auth/TLS, cung cấp cấu hình hiện có cho tiến trình query-api qua Compose override/
  secret injection; Compose gốc chỉ truyền URL, chưa truyền toàn bộ `OPENSEARCH_*`.
- `QUERY_API_PORT`: mặc định `8002`. `PUBLIC_ADDRESS`: domain HTTPS của gateway khi deploy;
  `:80` chỉ dành cho local HTTP. Gateway forward login/OPTIONS và Bearer headers tới API.
- `VITE_API_BASE_URL`: URL Query API public, HTTPS khi web dùng HTTPS. `web/.env.example`
  dùng `http://localhost:8002`, khớp Compose. Fallback lịch sử khi không set vẫn là `9002`,
  vì vậy luôn set biến này theo môi trường. Giá trị được nhúng lúc Vite build; đổi phải build lại.
- `VITE_JAEGER_URL`: tùy chọn, không mang JWT của Query API; để trống nếu không dùng Jaeger.

Không đặt JWT secret, seed password hoặc token vào Git. `.env.example` chỉ có secret/
credentials trống. `.env` được ignore nhưng vẫn chứa plaintext nếu bạn tự ghi credentials;
ưu tiên secret injection/prompt, giới hạn quyền đọc và xóa seed credentials khi xong.

## Seed và chạy bằng Compose

Các lệnh dưới đây là hướng dẫn thao tác trên môi trường được phép triển khai, không phải
báo cáo đã deploy. Cần Docker daemon hoạt động, OpenSearch healthy và Node/Python tương thích.

Ví dụ PowerShell 7: tạo secret cho môi trường local mới mà không in ra console, rồi lấy
admin credentials bằng prompt. Production phải lưu secret trong secret manager trước khi
khởi động; không sinh secret mới mỗi lần restart. Không thay secret đang dùng để seed lại.

```powershell
$env:JWT_SECRET = & python -c "import secrets; print(secrets.token_urlsafe(48))"
$credential = Get-Credential -Message "Admin account for initial seeding"
$env:ADMIN_SEED_USERNAME = $credential.UserName
$env:ADMIN_SEED_PASSWORD = $credential.GetNetworkCredential().Password
docker compose up -d --build opensearch ingestion query-api
docker compose run --rm --no-deps query-api python -m query-api.src.seed_admin
if ($LASTEXITCODE -ne 0) { throw "Admin seeding failed." }
# Chay lai cung lenh: Existing account preserved; no changes made.
Remove-Item Env:ADMIN_SEED_USERNAME, Env:ADMIN_SEED_PASSWORD
$credential = $null
docker compose up -d --force-recreate query-api
```

Xóa credentials khỏi `.env`/secret injection nếu đã nạp ở đó, rồi recreate query-api để
container không giữ seed password. Vẫn giữ `JWT_SECRET` ổn định. Chỉ bật/reload gateway và
deploy web sau khi được phép; không có auto seed khi API khởi động. Validate cấu hình:

```bash
docker compose --env-file .env.example config --quiet
# Khi daemon san sang, validate Caddy trong image hien co (khong deploy):
docker compose run --rm --no-deps gateway caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Seed tạo index nếu thiếu và chỉ dùng atomic create. Account đã tồn tại không đổi hash,
role hay timestamps, kể cả password mới được cấp qua env. Argon2id hash/salt được lưu;
không lưu password plaintext trong document, không log credentials. Lệnh không dùng để reset
password; exit 0 cho tạo mới/giữ account, exit 1 khi thiếu cấu hình hoặc lỗi OpenSearch/hash.

## Kiểm tra thủ công với hạ tầng thật

1. Seed như trên, mở `/login` trên web, nhập admin đã seed. Login JSON không gửi JWT.
   Thành công trả `{token, expires_at}`; web giữ hai field này trong memory/localStorage,
   rồi quay lại route nội bộ được yêu cầu hoặc Dashboard.
2. Mở Dashboard, Search và Incident View. Mỗi GET Query API mang Bearer token đúng base URL.
   Browser DevTools có thể kiểm tra request/status nhưng không chụp/chia sẻ token/password.
3. Kiểm tra thiếu/sai/hết hạn token đều 401 trên `/search`, `/clusters`, `/clusters/{id}`,
   `/clusters/{id}/history`. Dùng cluster ID đã có cho kiểm tra 200. `/health` luôn public.
4. Mở menu quản trị → Đăng xuất: storage/session và query/mutation cache được xóa, request
   đang chạy bị hủy, chuyển `/login`; mở URL được bảo vệ hoặc Back vẫn yêu cầu đăng nhập.
5. Trên môi trường test riêng, đặt lifetime ngắn để thử expiry: login, chờ quá `expires_at`,
   web chuyển login và API từ chối token cũ. Không rút ngắn lifetime production để chạy demo.

Ví dụ PowerShell 7 gọi API, chỉ in status/expiry, không in token:

```powershell
$base = "http://localhost:8002" # Hoac HTTPS gateway da duoc phep trien khai
(Invoke-WebRequest "$base/search" -SkipHttpErrorCheck).StatusCode # 401
(Invoke-WebRequest "$base/search" -Headers @{Authorization="Bearer invalid"} -SkipHttpErrorCheck).StatusCode # 401
$credential = Get-Credential -Message "Seeded admin login"
$body = @{username=$credential.UserName; password=$credential.GetNetworkCredential().Password} | ConvertTo-Json
$login = Invoke-RestMethod -Method Post "$base/auth/login" -ContentType "application/json" -Body $body
$body = $null
$credential = $null
$login.expires_at
$headers = @{Authorization="Bearer $($login.token)"}
(Invoke-WebRequest "$base/search?limit=5" -Headers $headers).StatusCode # 200
(Invoke-WebRequest "$base/clusters" -Headers $headers).StatusCode # 200
# Voi cluster_id that, GET /clusters/{id} va /clusters/{id}/history cung tra 200.
# Sau expires_at, cung headers phai tra 401 (them -SkipHttpErrorCheck de xem status).
```

CORS hiện cho `Origin: *`, methods GET/POST, headers Authorization/Content-Type, không
dùng cookie credentials. OPTIONS tới `/auth/login` (POST JSON) và protected endpoints (GET
Bearer) không cần JWT; cả response 401 có CORS headers. Gateway match chính xác `/auth/login`,
không route `/auth/register`; các route khác giữ nguyên. Khi test deployment, kiểm tra cả
OPTIONS qua gateway và reload trực tiếp `/login`/deep link trên Vercel (SPA rewrite có sẵn).

## Kiểm thử local không có cluster

Từ venv Query API đã cài `query-api/requirements-dev.txt`:

```bash
cd query-api
python -m pytest -q
cd ../web
npm ci
npm test
npm run build
npm run lint
npm run test:e2e -- --reporter=line
npm run test:auth-integration -- --reporter=line
```

Node phải tương thích lockfile (đã chạy bằng Node 24); Chrome theo cấu hình Playwright.
Suite integration cần `python` trên PATH trỏ tới venv Query API. Nó chạy web và FastAPI HTTP
thật trên `127.0.0.1:5174`/`:8023`, chỉ mock OpenSearch client, không mock HTTP login/query
trong browser. Secret/credentials sinh ngẫu nhiên, không persist; seed CLI chạy hai lần,
verify chữ ký/claims JWT, mọi protected route, CORS, missing/invalid/expired token, logout.
Pytest kiểm tra hash/schema/account preservation và body query hiện có. Harness nằm trong
`query-api/tests`, bị loại khỏi Docker image, tuyệt đối không dùng làm backend production.

Suite E2E mặc định có ba case dùng backend thật: cần `E2E_ADMIN_USERNAME`,
`E2E_ADMIN_PASSWORD`, backend/cluster có dữ liệu; thiếu credentials thì skip rõ ràng.
Không đưa tài khoản thật vào Playwright traces/video/log/artifacts. Suite integration riêng
tắt recording và dùng credentials tạm. Không cần live Jaeger.

## Giới hạn bảo mật và kiểm tra còn lại

- localStorage có thể bị JavaScript/XSS đọc; storage/guard không phải nguồn cấp quyền.
  Không lưu password ở browser. HTTPS, kiểm soát script/XSS và bảo vệ máy người dùng vẫn cần.
- Backend mới có quyền xác thực HS256/signature, claim/role/expiry. Không refresh token,
  denylist/revocation hay server logout; token sao chép trước logout vẫn dùng được tới `exp`.
  Role/password/user thay đổi cũng không thu hồi token cũ ngay. Đổi JWT secret làm vô hiệu
  toàn bộ token đã phát; cần kế hoạch phối hợp các replica.
- Chưa có login rate limit/lockout, MFA, issuer/audience binding hoặc password-reset API.
  CORS rộng cho web deploy khác origin; CORS không ngăn client ngoài browser gọi API.
- OpenSearch users index phải chỉ truy cập từ backend/hạ tầng được tin cậy. Stack nội bộ
  mặc định không có auth/TLS OpenSearch; cần hardening riêng cho môi trường production.
  Các route demo/Jaeger/docs public có sẵn không được JWT này bảo vệ.
- Không có deploy/merge trong bước này. Khi Docker/OpenSearch không sẵn sàng, test mock
  không xác nhận mapping/persistence/concurrency với cluster thật, Docker image build,
  gateway Caddy đang chạy, TLS/domain/firewall hoặc Vercel production. Ghi rõ các kiểm tra
  này chưa chạy; chỉ thay đổi source/cấu hình để sẵn sàng kiểm tra ở môi trường được phép.

## Evidence local ngày 2026-10-29

- Query API: `python -m pytest -q` — **213 passed**, một warning Starlette/httpx có sẵn.
- Web: `npm test` — **93 passed**. `npm run build` gồm `tsc -b` và production Vite build
  — pass, còn warning chunk lớn có sẵn. `npm run lint` — pass, bảy warning có sẵn.
- `npm run test:auth-integration -- --reporter=line` — **2 passed**: real browser + FastAPI
  HTTP, mock OpenSearch client. Seed CLI hai lần, login UI, JWT signature/claims, CORS,
  mọi protected API, missing/invalid/expired tokens, logout và chặn client sau logout.
- `npm run test:e2e -- --reporter=line --workers=1` — **7 passed, 3 skipped**. Ba case cần
  backend/cluster thật thiếu credentials E2E. Chạy tuần tự sau khi chạy nhiều tác vụ Vite/
  build đồng thời gây timeout; không thay đổi timeout hoặc bỏ assertion để lấy kết quả pass.
- `docker compose --env-file .env.example config --quiet` — pass. Rà soát gateway bổ sung
  `/auth/login`; chưa chạy Caddy validate/proxy vì Docker daemon không có.
  Compose JSON với credentials sinh tạm xác nhận cả năm biến auth được truyền đúng,
  secret chỉ vào query-api và danh sách services giữ nguyên so với trước auth.
- So sánh Git từ `916f530`: frozen contracts và `demo-app/`, `ingestion/`, `clustering/`
  không đổi trong toàn bộ auth work. Git chỉ theo dõi hai `.env.example`, secret/seed
  credentials trong đó đều trống. Rà soát source auth không thấy production secret literal;
  test credentials sinh tạm. Lockfile/dependencies web không đổi.

Không có Docker Desktop daemon, OpenSearch ở loopback không truy cập được và không có
remote OpenSearch được cấu hình. Vì vậy **chưa xác minh live seeding/OpenSearch persistence,
Docker build, gateway/TLS hoặc Vercel deploy**. Không claim các kiểm tra đó đã pass. Local
test processes đã được Playwright dừng sau test; không publish/deploy dịch vụ.

Các commit auth trước bước này đã rà soát trên `dev/manhpd`: `a8b5732` (config), `fafad48`
(OpenSearch users/seed), `4071325` (login/JWT), `8ee26db` (API guards), `fbfcbc9` (login UI),
`2f0160f` (frontend session/guards). Bước cuối bổ sung integration evidence, route login
gateway, env/docs và ngăn 422 login echo plaintext password; không đổi response thành công.
