import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AUTH_STORAGE_KEY, clearSession, getSession, restoreSession, saveSession,
  SessionExpiredError, useAuthStore,
} from "./auth";

describe("centralized auth session", () => {
  const session = { token: "test-token", expires_at: "2030-01-01T01:00:00+00:00" };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
    clearSession();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearSession();
    localStorage.clear();
    vi.useRealTimers();
  });

  it("persists only the token and expiration, never credentials or extra response fields", () => {
    const response = { ...session, username: "test-admin", password: "test-password" };
    saveSession(response);

    expect(getSession()).toEqual(session);
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(JSON.parse(localStorage.getItem(AUTH_STORAGE_KEY)!)).toEqual(session);
  });

  it("restores an unexpired persisted session after a reload", () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));

    restoreSession();

    expect(getSession()).toEqual(session);
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("expires and removes a session at its exact expiry boundary", () => {
    saveSession(session);
    vi.advanceTimersByTime(3_599_999);
    expect(getSession()).toEqual(session);

    vi.advanceTimersByTime(1);

    expect(getSession()).toBeNull();
    expect(useAuthStore.getState().status).toBe("expired");
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it("checks expiry on reads even if the browser timer has not run", () => {
    saveSession(session);
    vi.setSystemTime(new Date(session.expires_at));

    expect(getSession()).toBeNull();
    expect(useAuthStore.getState().status).toBe("expired");
  });

  it("removes expired sessions during restoration and reports expiration", () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ ...session, expires_at: "2020-01-01T00:00:00Z" }));

    restoreSession();

    expect(getSession()).toBeNull();
    expect(useAuthStore.getState().status).toBe("expired");
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it.each(["{broken", "null", '{}', '{"token":"","expires_at":"invalid"}'])(
    "discards malformed storage: %s", (stored) => {
      localStorage.setItem(AUTH_STORAGE_KEY, stored);

      restoreSession();

      expect(getSession()).toBeNull();
      expect(useAuthStore.getState().status).toBe("anonymous");
      expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    },
  );

  it("does not accept an already expired login response", () => {
    expect(() => saveSession({ ...session, expires_at: "2020-01-01T00:00:00Z" }))
      .toThrow(SessionExpiredError);
    expect(getSession()).toBeNull();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it("can use an in-memory session when persistence is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Blocked"); });

    expect(() => saveSession(session)).not.toThrow();
    expect(getSession()).toEqual(session);
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it("handles blocked storage on startup without crashing", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked"); });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("Blocked"); });

    expect(restoreSession).not.toThrow();
    expect(getSession()).toBeNull();
  });
});
