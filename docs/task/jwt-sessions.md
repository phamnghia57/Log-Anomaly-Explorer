# JWT sessions — issue #73

Design for review by Nghĩa. Refs #73. Baseline: main `33515bd`.

## Behavior

Access JWTs last 900 seconds by default. A login creates an independent session with an
absolute 604800-second expiry. Refresh rotates the refresh JWT without extending that expiry.
Logout revokes the browser session; changing account state, role, password or auth version
invalidates every account session. Requests starting authentication after the change is
acknowledged are rejected; already authorized in-flight work can finish.

## Storage and authorization

Use the existing OpenSearch cluster. `auth-sessions` stores username, auth_version,
refresh_hash (SHA-256, not indexed), created_at, expires_at and revoked_at; document ID is
a cryptographically random session ID. Only a refresh JWT hash is stored, never the token.
Each protected request validates its JWT and reads the session and current user by ID in
realtime. Storage failure returns 503. Missing, disabled, non-admin, expired or revoked
accounts/sessions return 401. Legacy JWTs without session/type/version claims are rejected.

Refresh JWTs are HS256, with distinct `token_use=refresh`, random `jti`, sub, sid, ver,
role, iat and exp. Access JWTs use `token_use=access`. Rotation uses OpenSearch sequence
number and primary term conditions. Reuse of a correctly signed retired refresh JWT
revokes its session; invalid signatures cannot revoke a session. Concurrent revocation
must never be overwritten by rotation.

Users gain optional enabled and auth_version fields; absent fields mean true and legacy.
New accounts and operator actions use a random version so re-enabling/recreating an
account cannot restore old grants. Only admin can log in; viewer reserves no API access.

## HTTP and browser contract

- POST /auth/login: unchanged JSON {token, expires_at}; sets refresh cookie.
- POST /auth/refresh: rotates cookie and returns the same access response shape.
- POST /auth/logout: revokes the current session and clears cookie; idempotent 204.
- Every auth POST requires X-CSRF-Protection: 1; a supplied Origin must match the explicit
  allowlist, and Origin: null is rejected. Auth responses, including errors, are no-store.
- Cookie lae_refresh: HttpOnly, host-only, SameSite=Lax, Path=/api/auth, Secure by default.
  Set AUTH_COOKIE_SECURE=false only for local HTTP testing.
- Expired access JWT responses include X-Auth-Reason: access_expired. Other 401s retain
  the existing generic error. A failed refresh never clears a potentially newer cookie.

The web calls /api on its own origin through Vercel/Vite. Access tokens live only in RAM;
startup refresh finishes before routing. A shared refresh promise and cross-tab Web Lock
serialize cookie-changing operations. BroadcastChannel synchronizes identity changes.
Only an explicit expired-access rejection can retry a business request once; network
errors/5xx never automatically retry POST. Logout only reports success after confirmation.

## Deployment and validation gates

Initialize storage explicitly before coordinated backend/web rollout. All backend replicas
must validate sessions; mixed old/new validators defeat revocation. Existing users log in
again. Proxy target is a build-time API_PROXY_TARGET HTTPS origin, separate from browser
VITE_API_BASE_URL=/api. Preserve Set-Cookie, Authorization and no-store through the proxy.

Required evidence: backend and web regressions, rotation/replay and logout races, account
revocation, real OpenSearch persistence/CAS across instances, browser reload/multiple tabs,
and Secure cookies on a real Vercel preview. Mock results do not prove deployment behavior.
Keep the PR draft with Refs #73 until review, CI and staging verification are complete.

## Configuration

- JWT_SECRET: existing secret manager value, mandatory, at least 32 UTF-8 bytes. Keep the
  same value across all replicas/restarts. Never put it in VITE variables or logs.
- JWT_EXPIRY_SECONDS: 900; AUTH_REFRESH_TTL_SECONDS: 604800. Positive integers, validated
  before tokens are issued. Access expiry is capped at the session's absolute expiry.
- USERS_INDEX: users; AUTH_SESSIONS_INDEX: auth-sessions. Use the existing cluster/client.
- AUTH_COOKIE_SECURE: true. Set false explicitly only for local HTTP development/tests.
- AUTH_ALLOWED_ORIGINS: comma-separated exact web origins (scheme/host/port, no path).
  Defaults to localhost:5173 and 127.0.0.1:5173 over HTTP. Configure production and each
  trusted preview explicitly; no wildcard or null origin. Missing Origin is supported
  for non-browser clients but the CSRF header remains mandatory.
- VITE_API_BASE_URL: /api. API_PROXY_TARGET: local backend origin for Vite, HTTPS backend
  origin for Vercel. Set Vercel Root Directory to web. Changing these values requires a build.
- OpenSearch credentials/TLS use the existing OPENSEARCH configuration. The internal
  cluster is not published by the production Compose file.

## Initialize and operate

Inject the existing OpenSearch/auth environment first; Python does not load .env automatically.
Run from the repository root using the project's Python environment:

```powershell
python -m query-api.src.manage_auth init
python -m query-api.src.seed_admin
python -m query-api.src.manage_auth disable admin-name
python -m query-api.src.manage_auth enable admin-name
python -m query-api.src.manage_auth set-role admin-name viewer
python -m query-api.src.manage_auth set-role admin-name admin
python -m query-api.src.manage_auth set-password admin-name
python -m query-api.src.manage_auth revoke-all admin-name
```

init is idempotent and does not seed users or alter existing passwords. seed_admin remains
create-only and needs ADMIN_SEED_USERNAME/PASSWORD; remove those seed values from runtime
after provisioning. set-password prompts twice without echo; passwords are not command
arguments. Every account action rotates its epoch in the same document update. Missing
users/storage return a generic failure and nonzero exit; nothing prints credentials.

For Compose, build the new query-api image, run the init command with `docker compose run
--rm query-api python -m query-api.src.manage_auth init`, then coordinate backend/gateway
and web release. Do not leave old validators serving traffic during the rollout. Existing
JWTs are rejected and users log in again. Keep the session index and mappings on rollback;
roll back all auth components together and rotate JWT_SECRET on every backend replica to
invalidate tokens issued by the new deployment.

Local web: set AUTH_COOKIE_SECURE=false and allow the Vite origin on the backend, run
Query API on :8002, and run npm run dev inside web with API_PROXY_TARGET=http://localhost:8002.
The browser still calls /api; the proxy strips that prefix before forwarding.

## Verification commands

```powershell
# Query API unit/regression tests, from its directory:
python -m pytest -q
# Real storage, on an isolated disposable cluster only:
$env:AUTH_TEST_OPENSEARCH_URL = 'http://127.0.0.1:19273'
python -m pytest tests/test_live_auth_sessions.py -v
# From web, with the Python environment on PATH:
npm run lint
npm run build
npm test
$env:AUTH_E2E_OPENSEARCH_URL = 'http://127.0.0.1:19273'
npm run test:auth-integration -- --reporter=line
```

Live suites create uniquely named test indexes and delete only those indexes on teardown.
Never point them at production. Browser tests generate ephemeral credentials, disable
trace/video/screenshots containing auth traffic and use an artificially short access TTL.
Without AUTH_E2E_OPENSEARCH_URL the dedicated browser suite uses the mock storage harness;
AUTH_TEST_OPENSEARCH_URL enables the real-storage pytest cases. CI has a separate live job
with OpenSearch 2.17.1 and a browser.

### Release checklist

- [ ] Nghĩa reviews auth contract and schema changes in PR #74.
- [ ] Required CI jobs pass on the final commit.
- [ ] Initialize the target users/session storage and configure web origins/proxy target.
- [ ] On an actual HTTPS Vercel preview, verify Secure/HttpOnly cookie creation, refresh,
  reload, Set-Cookie forwarding and copied-token rejection after logout.
- [ ] Verify account revocation against all backend replicas and record the release version.
- [ ] After review/staging approval, use Closes #73 and merge; verify the coordinated release.

Local browser and live-storage evidence does not claim Vercel preview or production rollout.
