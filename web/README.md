# web — Giao diện người dùng (Nghĩa)

Frontend cho Log Anomaly Explorer — UI riêng cho sản phẩm (không phải Swagger UI tự sinh),
bám đúng luồng "3. SEARCH & INCIDENT VIEW" trong `docs/architect/architecture-sod.png`.
Deploy lên Vercel; gọi trực tiếp `query-api` (Nghĩa) qua HTTP, không có backend riêng của
frontend (không có API route/BFF).

## Công nghệ

| Nhóm | Dùng |
|---|---|
| Nền tảng | React 19 + TypeScript + Vite |
| UI | Tailwind CSS v4 + shadcn/ui (Radix) + Lucide icons |
| Data fetching | TanStack Query |
| Bảng log | TanStack Table + TanStack Virtual (windowing — cụm có thể có hàng trăm log) |
| Biểu đồ | Apache ECharts (import modular, không load toàn bộ thư viện) |
| Form | React Hook Form + Zod |
| Routing | React Router |
| Thời gian | date-fns |
| Test | Vitest + React Testing Library (unit), Playwright (E2E) |

## Tính năng

- **Đăng nhập admin** (`/login`) — form username/password, loading, lỗi đăng nhập/kết nối,
  lưu phiên tập trung, quay lại trang đang mở sau đăng nhập và menu quản trị/đăng xuất.
- **Dashboard** (`/`) — thống kê nhanh (tổng cụm, alerted, anomalous, score cao nhất), biểu đồ
  top 10 cụm theo anomaly score, danh sách cụm dạng card (lọc theo status).
- **Incident View** (`/clusters/:id`) — chi tiết cụm (score, signature, first/last seen), biểu đồ
  **xu hướng anomaly score theo thời gian** (khi cụm đã có ≥ 2 điểm lịch sử), toàn bộ log liên
  quan (bảng ảo hoá, **phân trang** qua nút "Tải thêm log" — cụm hàng trăm log không tải hết một
  lần, xem `GET /clusters/{id}` mục `logs_limit`/`logs_offset`/`logs_total`), click 1 dòng mở
  Dialog xem stack trace/metadata, danh sách trace — click 1 trace nhảy sang Search đã lọc sẵn,
  **hoặc bấm icon ↗ cạnh trace để mở thẳng distributed trace đó trên Jaeger** (xem mục
  "Tracing / Jaeger" bên dưới), và panel **"Điều tra với AI Assistant"** — hỏi đáp về nguyên
  nhân/cách sửa, AI tự tra cứu dữ liệu thật (xem `query-api/README.md` mục "AI Assistant").
- **Search log** (`/search`) — lọc theo `service`, `trace_id`, từ khoá, thời gian; đồng bộ 2 chiều
  với URL (`?trace_id=...`) để có thể deep-link/chia sẻ link kết quả.

## Hợp đồng đang tuân theo

Gọi `POST /auth/login` và các query endpoints `GET /search`, `GET /clusters`,
`GET /clusters/{id}` (phân trang `logs` qua `logs_limit`/`logs_offset`) và
`GET /clusters/{id}/history` (dữ liệu chart xu hướng) — xem
[`../docs/architect/contracts/api-contract.md`](../docs/architect/contracts/api-contract.md).
Types trong [`src/lib/api.ts`](src/lib/api.ts) khớp với
[`log-schema.json`](../docs/architect/contracts/log-schema.json),
[`cluster-record.schema.json`](../docs/architect/contracts/cluster-record.schema.json) và
[`cluster-history-schema.json`](../docs/architect/contracts/cluster-history-schema.json).

## Đăng nhập và lưu phiên

Web gọi `/api` cùng origin qua Vite/Vercel proxy. Access token chỉ ở RAM, mặc định 15 phút;
refresh token nằm trong cookie HttpOnly và phiên hết hạn tuyệt đối sau 7 ngày. Reload chờ
refresh trước khi định tuyến. Web Locks tuần tự hóa login/refresh/logout giữa các tab;
BroadcastChannel đồng bộ thay tài khoản/đăng xuất và xóa cache cũ.

Access hết hạn được refresh; chỉ một lần gửi lại business request sau phản hồi xác nhận
`access_expired`. Lỗi mạng/5xx không tự gửi lại POST. Logout chỉ chuyển về login sau khi backend
xác nhận thu hồi; lỗi có thông báo để thử lại. Các JWT sao chép từ phiên đã logout bị backend từ chối.
Trình duyệt phải hỗ trợ Web Locks/BroadcastChannel. Token localStorage của bản cũ bị xóa.

Xem [runbook phiên JWT](../docs/task/jwt-sessions.md) cho cấu hình và migration.

## Tracing / Jaeger

`demo-app` đã gắn OpenTelemetry SDK thật (`src/telemetry.py`), sinh `trace_id`/`span_id` thật
cho mỗi request. Khi chạy `docker-compose.yml` ở gốc repo, service `jaeger` (Jaeger all-in-one,
nhận OTLP trực tiếp, không cần OTel Collector riêng) tự động nhận span từ `demo-app`.

Đặt `VITE_JAEGER_URL` (xem `.env.example`) trỏ tới Jaeger UI (`http://localhost:16686` khi dev
local) để UI hiện nút "Xem trace trên Jaeger" — bấm vào mở thẳng
`http://<jaeger>/trace/<trace_id>`, thấy được timeline span thật của request đã sinh ra lỗi đó.
Để trống biến này thì các nút/icon liên quan tới Jaeger tự ẩn, không báo lỗi.

**Lưu ý phạm vi**: `demo-app` KHÔNG gửi HTTP header lan truyền trace context
(`traceparent`) khi gọi `POST /ingest`, nên trace hiện tại chỉ gồm span phía `demo-app`
(request handler) — chưa phải trace đa dịch vụ xuyên `ingestion`/`clustering`. Vẫn đủ để xem
thời gian xử lý thật của từng request và liên kết đúng 1-1 với `trace_id` trong log.

## Chạy thử (dev local)

Cần `query-api` đang chạy thật (xem `docker-compose.yml` ở gốc repo hoặc
`query-api/README.md`), web gọi cùng origin qua `/api` và Vite chuyển tiếp tới `API_PROXY_TARGET`.
Backend local phải cho phép origin Vite và đặt AUTH_COOKIE_SECURE=false khi dùng HTTP.

```bash
# Từ thư mục gốc repo, dựng backend thật (gồm cả Jaeger):
docker compose up -d --build

cd web
npm install
cp .env.example .env.local
# VITE_API_BASE_URL=/api; API_PROXY_TARGET tro toi backend local (mac dinh :8002).
npm run dev                      # http://localhost:5173
```

## Test

```bash
npm run test          # unit test (Vitest + RTL) - mock fetch, khong can backend
npm run test:e2e -- e2e/login.spec.ts e2e/auth.spec.ts  # mock API, khong can backend
npm run test:auth-integration -- --reporter=line     # HTTP API that, chi mock OpenSearch
# Cac spec dashboard/incident can backend + cluster that va env
# E2E_ADMIN_USERNAME/E2E_ADMIN_PASSWORD cua admin da seed (khong commit credentials).
npm run test:e2e      # spec dung backend that duoc skip neu thieu credentials
npm run lint           # oxlint
npm run build          # type-check (tsc) + production build
```

Tests kiểm tra thành công/return destination an toàn, guard, loading và chống gửi lặp,
lỗi credentials/network, expiry, 401/không retry, Bearer đúng endpoint, abort request,
logout/xóa cache và navigation. Browser tests chạy Chrome theo cấu hình có sẵn, kiểm tra
cả mobile, reload và đăng xuất giữa hai tab. Build đã bao gồm typecheck
(`tsc -b`); có thể chạy riêng `npx tsc -b`. Dùng Node tương thích engine trong package-lock
(Vitest hiện hỗ trợ Node `^22.12`, `^24` hoặc `>=26`).

`test:auth-integration` cần Python của venv Query API trên PATH (dependencies từ
`query-api/requirements-dev.txt`) và Chrome theo cấu hình hiện có. Hai process riêng được
Playwright quản lý tại `127.0.0.1:8023` (FastAPI) và `127.0.0.1:5174` (web), không dùng lại
server đang chạy. Test tự sinh secret/credentials tạm và kiểm tra login, refresh, nhiều tab,
CSRF và logout qua proxy. Đặt AUTH_E2E_OPENSEARCH_URL để dùng OpenSearch thật; nếu không đặt,
client storage được mock. Trace/video tắt để không ghi credentials. Chỉ dùng cluster test riêng.
`npm run test:system-integration` chạy thêm các luồng Dashboard/Incident hiện có bằng tài khoản tạm.

Ví dụ PowerShell từ repo root sau khi đã cài dependencies:

```powershell
$env:PATH = "$PWD/.venv/Scripts;$env:PATH"
Set-Location web
npm run test:auth-integration -- --reporter=line
```

Trên Linux/macOS, activate venv Query API trước khi chạy npm. Các E2E cần backend thật dùng
`E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD` từ environment, không có credentials mặc định;
tránh lưu/chia sẻ Playwright traces chứa tài khoản thật. Không cần hai biến này cho suite
integration riêng vì nó tạo credentials tạm.

## Deploy lên Vercel

```bash
cd web
npx vercel login       # đăng nhập tài khoản Vercel của bạn (một lần)
npx vercel              # deploy preview
npx vercel --prod       # deploy production
```

Hoặc qua dashboard: Vercel → **Add New Project** → import repo GitHub này → **Root Directory**
đặt thành `web` (bắt buộc, vì đây là monorepo nhiều thư mục) → Vercel tự nhận diện Vite, không
cần cấu hình build command/output (mặc định `npm run build` → thư mục `dist/`).

**Bắt buộc** trên Vercel: `VITE_API_BASE_URL=/api`, `API_PROXY_TARGET=https://<backend-origin>`.
Proxy target phải là HTTPS origin không có path/credentials; cấu hình được đọc lúc build,
đổi phải redeploy. Backend đặt `AUTH_ALLOWED_ORIGINS` đúng origin của web production/preview
và `AUTH_COOKIE_SECURE=true`. Dùng đúng origin HTTPS của frontend production cho
`AUTH_ALLOWED_ORIGINS` và `CORS_WEB_ORIGIN` (không kèm path hay dấu gạch chéo cuối).
Nếu preview trỏ vào staging, cấu hình origin HTTPS cụ thể của preview ở staging.
Local mặc định cho phép Vite qua localhost hoặc 127.0.0.1 trong Query API, còn health
gọi trực tiếp qua Caddy dùng `CORS_WEB_ORIGIN`. Vercel root directory vẫn là `web`.

### Biến môi trường phải đặt cho CẢ scope Preview, không chỉ Production

Biến môi trường trên Vercel được phân theo scope (**Production** / **Preview** / **Development**),
và `vercel.ts` **throw** khi thiếu `API_PROXY_TARGET` (xem dòng 4–7 của file đó). Vercel bundle
`vercel.ts` bằng esbuild rồi **thực thi** nó để lấy config, nên thiếu biến là deployment **fail
ngay**, không phải fail lúc chạy. Hệ quả đã gặp thật: `API_PROXY_TARGET` chỉ đặt cho Production →
mọi deployment Production xanh, nhưng **mọi Preview deployment của mọi PR đều đỏ**, làm mỗi PR
mang một dấu X trong khi test thật đều pass.

Kiểm tra lại đúng cơ chế Vercel dùng, không cần deploy thử:

```bash
cd web && npm test -- proxy.test.ts
```

Sửa: Vercel → **Settings → Environment Variables**, đặt `VITE_API_BASE_URL`, `API_PROXY_TARGET`
và `VITE_JAEGER_URL` cho **cả Preview** (dự án này không có backend staging riêng nên trỏ cùng
Caddy gateway như Production), rồi redeploy lại PR để check chuyển xanh. Nếu không muốn dùng
Preview deployment thì tắt hẳn trong **Settings → Git** — đừng nới lỏng guard trong `vercel.ts`,
vì khi đó preview sẽ build thành công nhưng không có rewrite `/api`, tức là lỗi âm thầm lúc chạy
thay vì lỗi rõ ràng lúc build.

Lưu ý thêm: URL preview đổi theo từng deployment, nên đăng nhập **từ** trang preview chỉ hoạt động
khi origin preview nằm trong `AUTH_ALLOWED_ORIGINS` của backend. Chỉ cần check CI xanh thì không
bắt buộc bước này — build thành công là đủ.

`vercel.ts` xuất cấu hình qua `default` và tạo rewrite bằng helper `routes.rewrite()`.
Chạy `npm test -- proxy.test.ts` để kiểm tra cấu hình sau khi bundle bằng esbuild,
thực thi trong Node và serialize thành JSON; test dùng bộ kiểm tra routing của Vercel
để xác minh `/api/auth/refresh` được chuyển đúng tới backend trước SPA fallback.

- `VITE_JAEGER_URL` cũng phải HTTPS nếu muốn nút "Xem trace trên Jaeger" hoạt động từ trang
  Vercel — hoặc để trống nếu Jaeger chỉ chạy nội bộ (nút sẽ tự ẩn).

### Lấy URL HTTPS cho backend (gateway Caddy)

`docker-compose.yml` ở gốc repo có service `gateway` (Caddy) tự xin HTTPS qua Let's Encrypt —
xem [`deploy/Caddyfile`](../deploy/Caddyfile). Bắt buộc dùng đúng port 80/443 (yêu cầu của
Let's Encrypt, không đổi được).

**Nếu máy chủ đang có tiến trình khác chiếm sẵn port 80/443**, cần giải phóng trước khi bật
gateway này (kiểm tra bằng `sudo lsof -i :80` hoặc `sudo ss -tlnp | grep :80`).

Bật gateway, trỏ `PUBLIC_ADDRESS` sang một host sslip.io dựa trên IP public của máy chủ (vd.
IP là `20.1.2.3` → `20-1-2-3.sslip.io`):
```bash
echo "PUBLIC_ADDRESS=20-1-2-3.sslip.io" >> .env   # thay IP that cua may chu
docker compose up -d --build gateway
docker compose logs gateway --tail 20              # doi thay "certificate obtained successfully"
curl https://20-1-2-3.sslip.io/health               # phai tra ve {"status":"ok",...}
```
`https://20-1-2-3.sslip.io` chính là giá trị đặt cho `API_PROXY_TARGET` trên Vercel.

Jaeger UI cũng được route qua cùng domain tại `/jaeger` (xem `@jaeger` trong `deploy/Caddyfile`
và `QUERY_BASE_PATH=/jaeger` trong `docker-compose.yml`):
```bash
curl -sI https://20-1-2-3.sslip.io/jaeger    # phai tra 200, khong phai 404
```
`https://20-1-2-3.sslip.io/jaeger` chính là giá trị đặt cho `VITE_JAEGER_URL` trên Vercel.

## Evidence sở hữu

Phần của checklist "Search, Incident view" (MVP bắt buộc, xem `README.md` gốc) — UI thật
thay cho việc chỉ test qua Swagger UI/`curl`.

## Search: histogram/facets và trang Trạng thái hệ thống (Minh)

- Trang `/search` có filter level, histogram theo giờ và facet theo level/service; gọi `GET /search/aggregations` tại Query API. Đòi hỏi JWT admin giống `/search`.
- Sidebar thêm `/system-status`, gọi `/health` của Query API, Ingestion và Demo App mỗi 15 giây; hiển thị xanh (ok) / đỏ (degraded hoặc unreachable).
- Khi frontend truy cập bằng HTTPS (Vercel), các URL health **phải** qua Caddy gateway HTTPS, không gọi trực tiếp cổng Docker HTTP. Đặt `VITE_API_BASE_URL=/api`, `API_PROXY_TARGET=https://<backend-domain>` và (tùy chọn) `VITE_INGESTION_HEALTH_URL=https://<backend-domain>/ingestion/health`, `VITE_DEMO_HEALTH_URL=https://<backend-domain>/demo/health`. Caddy chỉ mở health ingestion, không mở ingest public.
- Khi dùng local query-api tại `:8002` nhưng gateway tại `:80`, cấu hình health URLs trong `web/.env.local` theo ví dụ `.env.example`.

### Auth browser tests với OpenSearch thật

Đặt `AUTH_E2E_OPENSEARCH_URL` tới cluster test riêng rồi chạy `npm run test:auth-integration`.
Suite tự tạo index/credentials tạm và kiểm tra cookie, proxy, refresh, nhiều tab, CSRF và logout.
Không đặt biến này tới production. Xem runbook JWT sessions; CI có job riêng dùng OpenSearch 2.17.1.
