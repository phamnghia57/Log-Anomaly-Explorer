import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AdminMenu } from "@/components/auth/AdminMenu";
import { AUTH_STORAGE_KEY, clearSession, getSession, saveSession, SESSION_EXPIRED_MESSAGE } from "@/lib/auth";
import App from "./App";

const session = () => ({ token: "test-admin-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() });

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{JSON.stringify({
    path: `${location.pathname}${location.search}${location.hash}`, state: location.state,
  })}</div>;
}

describe("frontend authentication integration", () => {
  const fetchMock = vi.fn();
  let queryClient: QueryClient;

  function renderApp(path = "/", state?: unknown) {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[{ pathname: path.split(/[?#]/)[0],
          search: path.includes("?") ? `?${path.split("?")[1].split("#")[0]}` : "",
          hash: path.includes("#") ? `#${path.split("#")[1]}` : "", state }]}>
          <TooltipProvider><App /><LocationProbe /></TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  function cachePrivateState() {
    queryClient.setQueryData(["private-log"], { message: "private" });
    queryClient.getMutationCache().build(queryClient, { mutationKey: ["private-mutation"] });
  }

  function expectEmptyCache() {
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
  }

  beforeEach(() => {
    clearSession();
    localStorage.clear();
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, retryDelay: 0 } } });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
    fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ total: 0, clusters: [] }))));
  });

  afterEach(() => {
    cleanup();
    queryClient.clear();
    clearSession();
    localStorage.clear();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it.each(["/", "/search?trace_id=abc#results", "/clusters/c1"])(
    "redirects anonymous users from %s before rendering or fetching protected data", async (path) => {
      renderApp(path);

      expect(await screen.findByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
      expect(JSON.parse(screen.getByTestId("location").textContent!)).toEqual({ path: "/login", state: { from: path } });
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("allows an admin to load the dashboard and use the existing sidebar navigation", async () => {
    const current = session();
    saveSession(current);
    renderApp();
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeVisible();
    await waitFor(() => expect(queryClient.getQueryData(["clusters", ""])).toEqual({ total: 0, clusters: [] }));
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${current.token}`);
    expect(screen.getByRole("button", { name: "Menu quản trị" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Đăng nhập" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Search log" }));
    expect(await screen.findByRole("heading", { name: "Search log" })).toBeVisible();
    await user.click(screen.getByRole("link", { name: "Dashboard" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeVisible();
  });

  it("clears the rejected session and all cached data on 401, redirects once, and does not retry", async () => {
    saveSession(session());
    cachePrivateState();
    fetchMock.mockImplementation(() => Promise.resolve(new Response("Unauthorized", { status: 401 })));
    renderApp("/search?trace_id=abc");

    expect(await screen.findByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(SESSION_EXPIRED_MESSAGE);
    expect(getSession()).toBeNull();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    expectEmptyCache();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(screen.getByTestId("location").textContent!)).toEqual({ path: "/login", state: { from: "/search?trace_id=abc" } });
  });

  it("expires an open protected page, clears private cache and returns to login", () => {
    vi.useFakeTimers();
    saveSession({ token: "short-test-token", expires_at: new Date(Date.now() + 2_000).toISOString() });
    renderApp("/search");
    cachePrivateState();
    expect(screen.getByRole("heading", { name: "Search log" })).toBeVisible();

    act(() => { vi.advanceTimersByTime(2_000); });

    expect(screen.getByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(SESSION_EXPIRED_MESSAGE);
    expectEmptyCache();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never treats an expired session as authenticated even when its timer has not run", async () => {
    vi.useFakeTimers();
    const current = session();
    saveSession(current);
    vi.setSystemTime(new Date(current.expires_at));

    renderApp();

    expect(screen.getByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
    expect(getSession()).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("logs out through the admin menu, aborts pending requests and clears query/mutation caches", async () => {
    saveSession(session());
    let signal: AbortSignal | undefined;
    fetchMock.mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      signal = options.signal;
      signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    renderApp();
    cachePrivateState();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Menu quản trị" }));
    expect(screen.getByText("Tài khoản admin")).toBeVisible();
    await user.click(screen.getByRole("menuitem", { name: "Đăng xuất" }));

    expect(await screen.findByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
    expect(getSession()).toBeNull();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    expectEmptyCache();
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByRole("button", { name: "Menu quản trị" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each([AUTH_STORAGE_KEY, null])("handles logout/storage clear in another tab (%s) and clears private cache", async (key) => {
    saveSession(session());
    renderApp("/search");
    cachePrivateState();

    act(() => {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      window.dispatchEvent(new StorageEvent("storage", { key }));
    });

    expect(await screen.findByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
    expectEmptyCache();
  });

  it("keeps a valid logged-in admin out of /login without making a loop", async () => {
    saveSession(session());
    renderApp("/login", { from: "/search?trace_id=abc" });
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ total: 0, results: [] })));

    expect(await screen.findByRole("heading", { name: "Search log" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Đăng nhập quản trị" })).not.toBeInTheDocument();
  });

  it("shows a login link rather than the admin menu when anonymous", () => {
    render(<QueryClientProvider client={queryClient}><MemoryRouter><AdminMenu /></MemoryRouter></QueryClientProvider>);
    expect(screen.getByRole("link", { name: "Đăng nhập" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: "Menu quản trị" })).not.toBeInTheDocument();
  });
});
