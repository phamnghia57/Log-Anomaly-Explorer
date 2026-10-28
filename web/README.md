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
  lưu phiên tập trung và chuyển tới Dashboard khi thành công.
- **Dashboard** (`/`) — thống kê nhanh (tổng cụm, alerted, anomalous, score cao nhất), biểu đồ
  top 10 cụm theo anomaly score, danh sách cụm dạng card (lọc theo status).
- **Incident View** (`/clusters/:id`) — chi tiết cụm (score, signature, first/last seen), toàn bộ
  log liên quan (bảng ảo hoá, click 1 dòng mở Dialog xem stack trace/metadata), danh sách
  trace — click 1 trace nhảy sang Search đã lọc sẵn, **hoặc bấm icon ↗ cạnh trace để mở thẳng
  distributed trace đó trên Jaeger** (xem mục "Tracing / Jaeger" bên dưới).
- **Search log** (`/search`) — lọc theo `service`, `trace_id`, từ khoá, thời gian; đồng bộ 2 chiều
  với URL (`?trace_id=...`) để có thể deep-link/chia sẻ link kết quả.

## Hợp đồng đang tuân theo

Gọi `POST /auth/login` và các query endpoints `GET /search`, `GET /clusters`, `GET /clusters/{id}`
— xem [`../docs/architect/contracts/api-contract.md`](../docs/architect/contracts/api-contract.md).
Types trong [`src/lib/api.ts`](src/lib/api.ts) khớp với
[`log-schema.json`](../docs/architect/contracts/log-schema.json) và
[`cluster-record.schema.json`](../docs/architect/contracts/cluster-record.schema.json).

## Đăng nhập và lưu phiên

Mở `/login`, nhập tài khoản admin đã seed trong OpenSearch (xem
[`query-api/README.md`](../query-api/README.md)). Form gửi JSON tới
`${VITE_API_BASE_URL}/auth/login`, dùng cùng cấu hình API base URL với dashboard.
Backend cần `JWT_SECRET` riêng và admin đã seed; không có signup hoặc credentials mặc định.
Nếu đi qua reverse proxy, proxy phải route `POST /auth/login` tới query-api. Gateway Caddy
hiện chưa có route login; cập nhật gateway thuộc bước tích hợp sau. Dev có thể gọi trực tiếp
cổng query-api.

Thành công: đọc `token`/`expires_at`, lưu qua `src/lib/auth.ts` (Zustand), xóa query cache cũ
và chuyển tới `/` bằng React Router với `replace`. Client API chung đính kèm Bearer token
cho query requests để dashboard tải được dữ liệu sau đăng nhập. Không đổi layout dashboard.

Module auth chỉ lưu `{ token, expires_at }` dưới key `log-anomaly-explorer.auth` trong
localStorage; không lưu username/password. Mật khẩu chỉ ở form/request trong bộ nhớ và được
xóa khỏi form sau mỗi lần gửi. Response lỗi không được lưu; lỗi credentials hiển thị chung,
không đưa chi tiết backend vào UI. Form có thông báo riêng cho lỗi mạng/dịch vụ không sẵn sàng.

Phiên còn hạn được restore khi reload/mở lại trình duyệt. Hết hạn được xóa bằng timer và
kiểm tra lại trước API request; `/login` hiển thị thông báo đăng nhập lại. API trả 401 sẽ
xóa phiên bị từ chối; 401 của request cũ không xóa phiên mới vừa đăng nhập. Thay đổi storage
giữa các tab được đồng bộ. Nếu browser chặn storage/hết quota, phiên chỉ tồn tại trong
memory đến khi reload. Dữ liệu persisted hỏng/hết hạn được loại bỏ.

**Tradeoff bảo mật:** localStorage tiện restore phiên nhưng JavaScript cùng origin có thể
đọc token; XSS có thể đánh cắp nó, và dữ liệu storage không phải nguồn đáng tin cậy. Đây là
tradeoff của client Bearer JWT hiện tại. [OWASP khuyến cáo tránh lưu session identifier
trong localStorage](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html#local-storage);
cookie HttpOnly giảm khả năng script đọc token nhưng cần thiết kế lại cơ chế cookie/BFF
và CSRF ở backend. Chưa chuyển sang cơ chế đó trong bước này. Dùng HTTPS khi deploy,
không log token/password, không đưa `JWT_SECRET` vào biến `VITE_*`. Expiry ở client chỉ hỗ trợ
UX; backend vẫn phải kiểm tra signature/role/expiration cho mọi query được bảo vệ.

Bước này chưa thêm global route guard, logout UI hay tự điều hướng toàn app khi 401.
Mở `/login` trực tiếp khi cần đăng nhập lại; enforcement truy cập dữ liệu nằm ở backend.

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
`query-api/README.md`), vì CORS trên `query-api` đã mở sẵn cho frontend gọi trực tiếp
(`allow_origins=["*"]`, cho `GET`, `POST` và preflight với header Authorization — xem
`query-api/src/main.py`).

```bash
# Từ thư mục gốc repo, dựng backend thật (gồm cả Jaeger):
docker compose up -d --build

cd web
npm install
cp .env.example .env.local
# Sua VITE_API_BASE_URL khop cong backend: Compose mac dinh http://localhost:8002.
npm run dev                      # http://localhost:5173
```

## Test

```bash
npm run test          # unit test (Vitest + RTL) - mock fetch, khong can backend
npm run test:e2e -- e2e/login.spec.ts  # login E2E: mock API, khong can backend
npm run test:e2e      # E2E (Playwright) - CAN backend that dang chay + it nhat 1 cluster co san
npm run lint           # oxlint
npm run build          # type-check (tsc) + production build
```

Login tests kiểm tra thành công/redirect, loading và chống gửi lặp, lỗi credentials/network,
session expired, persistence chỉ có token/expiry, restore và Bearer headers. Browser tests
chạy Chrome theo cấu hình có sẵn, kiểm tra cả mobile và reload. Build đã bao gồm typecheck
(`tsc -b`); có thể chạy riêng `npx tsc -b`. Dùng Node tương thích engine trong package-lock
(Vitest hiện hỗ trợ Node `^22.12`, `^24` hoặc `>=26`).

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

**Bắt buộc**: trong Vercel → Project Settings → Environment Variables, thêm
`VITE_API_BASE_URL` trỏ tới URL **public, HTTPS** của `query-api` đã deploy. Hai lưu ý quan trọng:

- Biến này được nhúng vào bundle **lúc build**, không phải lúc chạy — đổi giá trị trên Vercel
  xong phải **Redeploy** mới có hiệu lực, chỉ sửa biến không tự áp dụng cho bản đã build.
- Backend phải là **HTTPS**, không phải HTTP thuần — Vercel phục vụ trang qua HTTPS nên trình
  duyệt sẽ chặn (Mixed Content) nếu gọi sang một API HTTP thuần.
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
`https://20-1-2-3.sslip.io` chính là giá trị đặt cho `VITE_API_BASE_URL` trên Vercel.

Jaeger UI cũng được route qua cùng domain tại `/jaeger` (xem `@jaeger` trong `deploy/Caddyfile`
và `QUERY_BASE_PATH=/jaeger` trong `docker-compose.yml`):
```bash
curl -sI https://20-1-2-3.sslip.io/jaeger    # phai tra 200, khong phai 404
```
`https://20-1-2-3.sslip.io/jaeger` chính là giá trị đặt cho `VITE_JAEGER_URL` trên Vercel.

## Evidence sở hữu

Phần của checklist "Search, Incident view" (MVP bắt buộc, xem `README.md` gốc) — UI thật
thay cho việc chỉ test qua Swagger UI/`curl`.
