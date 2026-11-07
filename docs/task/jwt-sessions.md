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
