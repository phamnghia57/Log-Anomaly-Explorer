import { create } from "zustand";
import { API_BASE_URL, ApiError } from "./api-base";

export interface AuthSession { token: string; expires_at: string }
type AuthStatus = "initializing" | "anonymous" | "authenticated" | "expired" | "unavailable";
export const AUTH_STORAGE_KEY = "log-anomaly-explorer.auth"; // remove legacy tokens only
export const SESSION_EXPIRED_MESSAGE = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.";
export class SessionExpiredError extends Error {
  constructor() { super(SESSION_EXPIRED_MESSAGE); }
}
export const useAuthStore = create<{
  session: AuthSession | null; status: AuthStatus; generation: number;
}>(() => ({ session: null, status: "initializing", generation: 0 }));

let expiryTimer: number | undefined;
let refreshing: Promise<AuthSession> | undefined;
let channel: BroadcastChannel | undefined;

export function isAuthSession(value: unknown): value is AuthSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Partial<AuthSession>;
  return typeof session.token === "string" && session.token.trim().length > 0
    && typeof session.expires_at === "string" && Number.isFinite(Date.parse(session.expires_at));
}
function removeLegacyToken() {
  try { window.localStorage.removeItem(AUTH_STORAGE_KEY); } catch { /* memory auth works without storage */ }
}
export function clearSession(status: "anonymous" | "expired" = "anonymous") {
  window.clearTimeout(expiryTimer);
  expiryTimer = undefined;
  removeLegacyToken();
  useAuthStore.setState((state) => ({ session: null, status, generation: state.generation + 1 }));
}
export function saveSession(value: AuthSession) {
  if (!isAuthSession(value)) throw new Error("Phản hồi đăng nhập không hợp lệ.");
  if (Date.parse(value.expires_at) <= Date.now()) throw new SessionExpiredError();
  removeLegacyToken();
  const session = { token: value.token, expires_at: value.expires_at };
  useAuthStore.setState({ session, status: "authenticated" });
  window.clearTimeout(expiryTimer);
  expiryTimer = window.setTimeout(() => { void refreshSession(true).catch(() => {}); },
    Math.min(Math.max(1, Date.parse(session.expires_at) - Date.now()), 2_147_483_647));
}
// An expired access token may still belong to a refreshable session.
export function getSession() { return useAuthStore.getState().session; }
export function authGeneration() { return useAuthStore.getState().generation; }

async function authLock<T>(callback: () => Promise<T>): Promise<T> {
  if (!navigator.locks) throw new ApiError("Trình duyệt cần hỗ trợ Web Locks để đăng nhập an toàn.", 0);
  return navigator.locks.request("lae-auth-session", callback);
}
async function authPost(action: "login" | "refresh" | "logout", payload?: Record<string, string>) {
  if (new URL(API_BASE_URL).origin !== window.location.origin) {
    throw new ApiError("Cần cấu hình API qua /api trên cùng địa chỉ với web.", 0);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/auth/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Protection": "1" },
      body: JSON.stringify(payload ?? {}), credentials: "same-origin", cache: "no-store", redirect: "error",
    });
  } catch {
    throw new ApiError("Không kết nối được máy chủ. Vui lòng thử lại.", 0);
  }
  if (!response.ok) throw new ApiError(response.status >= 500
    ? "Dịch vụ đăng nhập tạm thời không khả dụng. Vui lòng thử lại."
    : action === "login" ? "Đăng nhập không thành công. Vui lòng kiểm tra tên đăng nhập và mật khẩu."
    : SESSION_EXPIRED_MESSAGE, response.status);
  return response;
}
async function readSession(response: Response) {
  const body: unknown = await response.json().catch(() => null);
  if (!isAuthSession(body)) throw new ApiError("Không thể hoàn tất đăng nhập. Vui lòng thử lại.", 502);
  return { token: body.token, expires_at: body.expires_at };
}

export async function loginSession(username: string, password: string): Promise<AuthSession> {
  clearSession();
  const generation = authGeneration();
  return authLock(async () => {
    if (generation !== authGeneration()) throw new SessionExpiredError();
    const session = await readSession(await authPost("login", { username, password }));
    if (generation !== authGeneration()) throw new SessionExpiredError();
    saveSession(session);
    channel?.postMessage("login");
    return session;
  });
}

export function refreshSession(force = false): Promise<AuthSession> {
  if (refreshing) return refreshing;
  const current = getSession();
  if (!force && current && Date.parse(current.expires_at) > Date.now()) return Promise.resolve(current);
  const generation = authGeneration();
  const task = authLock(async () => {
    if (generation !== authGeneration()) throw new SessionExpiredError();
    const session = await readSession(await authPost("refresh"));
    if (generation !== authGeneration()) throw new SessionExpiredError();
    saveSession(session);
    return session;
  }).catch((error: unknown) => {
    if (generation === authGeneration()) {
      if (error instanceof ApiError && error.status === 401) clearSession(current ? "expired" : "anonymous");
      else useAuthStore.setState({ status: "unavailable" });
    }
    throw error;
  });
  refreshing = task;
  void task.finally(() => { if (refreshing === task) refreshing = undefined; }).catch(() => {});
  return task;
}

export async function logoutSession() {
  // Keep the UI honest: a network failure must not be reported as server logout.
  await authLock(async () => {
    await authPost("logout");
    clearSession();
    channel?.postMessage("logout");
  });
}
export function restoreSession() {
  removeLegacyToken();
  if (!getSession()) useAuthStore.setState({ status: "initializing" });
  return refreshSession(true);
}
export function startAuthSync() {
  if (typeof BroadcastChannel === "undefined") return () => {};
  const connection = new BroadcastChannel("lae-auth-session");
  channel = connection;
  connection.onmessage = (event) => {
    if (event.data !== "login" && event.data !== "logout") return;
    clearSession();
    if (event.data === "login") {
      // The pending request from the previous identity is discarded before restoring.
      const old = refreshing;
      void Promise.resolve(old).catch(() => {}).then(() => restoreSession()).catch(() => {});
      useAuthStore.setState({ status: "initializing" });
    }
  };
  return () => { connection.close(); if (channel === connection) channel = undefined; };
}
