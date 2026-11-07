import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTH_STORAGE_KEY, clearSession, getSession, loginSession, logoutSession, refreshSession,
  restoreSession, saveSession, SessionExpiredError, useAuthStore } from "./auth";

describe("persistent server sessions with memory-only access", () => {
  const fetchMock = vi.fn();
  const session = () => ({ token: "test-token", expires_at: new Date(Date.now() + 900_000).toISOString() });
  beforeEach(() => { clearSession(); localStorage.clear(); vi.stubGlobal("fetch", fetchMock); });
  afterEach(() => { clearSession(); fetchMock.mockReset(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("stores access only in RAM and removes legacy persisted tokens", () => {
    localStorage.setItem(AUTH_STORAGE_KEY, "old-token");
    const value = session();
    saveSession({ ...value, password: "never-save" } as typeof value);
    expect(getSession()).toEqual(value);
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });
  it("restores by rotating the cookie, ignoring even valid-looking localStorage", async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session()));
    const fresh = { ...session(), token: "server-issued" };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(fresh)));
    await restoreSession();
    expect(getSession()).toEqual(fresh);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/auth/refresh"), expect.objectContaining({
      credentials: "same-origin", headers: expect.objectContaining({ "X-CSRF-Protection": "1" }),
    }));
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });
  it("shares one refresh for concurrent callers", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(session())));
    const [first, second] = await Promise.all([refreshSession(true), refreshSession(true)]);
    expect(first).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("refreshes expired access instead of treating its expiry as the end of the session", async () => {
    const current = session();
    saveSession(current);
    vi.spyOn(Date, "now").mockReturnValue(Date.parse(current.expires_at) + 1);
    const fresh = session();
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(fresh)));
    await refreshSession();
    expect(getSession()).toEqual(fresh);
  });
  it("cannot restore a session from a response arriving after logout", async () => {
    let complete!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { complete = resolve; }));
    const pending = refreshSession(true);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    clearSession();
    complete(new Response(JSON.stringify(session())));
    await expect(pending).rejects.toBeInstanceOf(SessionExpiredError);
    expect(getSession()).toBeNull();
  });
  it("keeps a working session when logout cannot be confirmed", async () => {
    const current = session(); saveSession(current);
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    await expect(logoutSession()).rejects.toMatchObject({ status: 0 });
    expect(getSession()).toEqual(current);
  });
  it("clears memory only after confirmed server logout", async () => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await logoutSession();
    expect(getSession()).toBeNull();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/auth/logout");
  });
  it("turns rejected refresh into anonymous startup and expired active session", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    await expect(restoreSession()).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().status).toBe("anonymous");
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    await expect(refreshSession(true)).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().status).toBe("expired");
  });
  it("shows unavailable on storage/network failure without presenting logout success", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 503 }));
    await expect(restoreSession()).rejects.toMatchObject({ status: 503 });
    expect(useAuthStore.getState().status).toBe("unavailable");
  });
  it("rejects expired login responses", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ ...session(), expires_at: "2000-01-01T00:00:00Z" })));
    await expect(loginSession("user", "password")).rejects.toBeInstanceOf(SessionExpiredError);
    expect(getSession()).toBeNull();
  });
  it("works with blocked legacy storage", async () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("Blocked"); });
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(session())));
    await expect(restoreSession()).resolves.toMatchObject({ token: "test-token" });
  });
  it("does not silently fall back to unlocked rotation in an unsupported browser", async () => {
    Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
    await expect(loginSession("user", "password")).rejects.toMatchObject({ status: 0 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
