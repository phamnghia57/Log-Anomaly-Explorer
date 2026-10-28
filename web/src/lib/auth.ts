import { create } from "zustand";

export interface AuthSession {
  token: string;
  expires_at: string;
}

type AuthStatus = "anonymous" | "authenticated" | "expired";

export const AUTH_STORAGE_KEY = "log-anomaly-explorer.auth";
export const SESSION_EXPIRED_MESSAGE = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.";

export class SessionExpiredError extends Error {
  constructor() {
    super(SESSION_EXPIRED_MESSAGE);
  }
}

export const useAuthStore = create<{ session: AuthSession | null; status: AuthStatus }>(() => ({
  session: null,
  status: "anonymous",
}));

let expiryTimer: number | undefined;

export function isAuthSession(value: unknown): value is AuthSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Partial<AuthSession>;
  return typeof session.token === "string" && session.token.trim().length > 0
    && typeof session.expires_at === "string" && Number.isFinite(Date.parse(session.expires_at));
}

function removeStoredSession() {
  try {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
  } catch {
    // Storage co the bi browser chan; session trong memory van duoc xoa.
  }
}

export function clearSession(status: "anonymous" | "expired" = "anonymous") {
  window.clearTimeout(expiryTimer);
  expiryTimer = undefined;
  removeStoredSession();
  useAuthStore.setState({ session: null, status });
}

function scheduleExpiration(session: AuthSession) {
  window.clearTimeout(expiryTimer);
  const delay = Math.max(0, Date.parse(session.expires_at) - Date.now());
  expiryTimer = window.setTimeout(() => {
    const current = getSession();
    if (current) scheduleExpiration(current);
  }, Math.min(delay, 2_147_483_647));
}

export function saveSession(value: AuthSession) {
  if (!isAuthSession(value)) {
    clearSession();
    throw new Error("Phản hồi đăng nhập không hợp lệ.");
  }
  if (Date.parse(value.expires_at) <= Date.now()) {
    clearSession("expired");
    throw new SessionExpiredError();
  }
  // Chi luu hai field can thiet; khong luu credentials/field du trong response.
  const session = { token: value.token, expires_at: value.expires_at };
  try {
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
  } catch {
    removeStoredSession();
    // Neu storage bi chan/het quota, chi giu session trong memory den khi reload.
  }
  useAuthStore.setState({ session, status: "authenticated" });
  scheduleExpiration(session);
}

export function getSession(): AuthSession | null {
  const session = useAuthStore.getState().session;
  if (session && Date.parse(session.expires_at) <= Date.now()) {
    clearSession("expired");
    return null;
  }
  return session;
}

export function restoreSession() {
  try {
    const stored = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!stored) {
      clearSession();
      return;
    }
    const parsed: unknown = JSON.parse(stored);
    if (!isAuthSession(parsed)) {
      clearSession();
      return;
    }
    saveSession(parsed);
  } catch (error) {
    if (!(error instanceof SessionExpiredError)) clearSession();
  }
}
