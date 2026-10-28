import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL } from "@/lib/api";
import {
  AUTH_STORAGE_KEY, clearSession, getSession, restoreSession, saveSession,
  SESSION_EXPIRED_MESSAGE,
} from "@/lib/auth";
import { LoginPage } from "./LoginPage";

describe("admin login page", () => {
  const fetchMock = vi.fn();
  const session = () => ({ token: "test-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() });

  function renderLogin() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(["previous-private-data"], { private: true });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/login"]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<h1>Dashboard</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    return { user: userEvent.setup(), queryClient };
  }

  async function fillForm(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText("Tên đăng nhập"), "test-admin");
    await user.type(screen.getByLabelText("Mật khẩu"), "test-password");
  }

  beforeEach(() => {
    clearSession();
    localStorage.clear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    clearSession();
    localStorage.clear();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("renders an accessible password form and validates required fields without a request", async () => {
    const { user } = renderLogin();
    expect(screen.getByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
    expect(screen.getByLabelText("Mật khẩu")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Mật khẩu")).toHaveAttribute("autocomplete", "current-password");

    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByText("Vui lòng nhập tên đăng nhập.")).toBeVisible();
    expect(screen.getByText("Vui lòng nhập mật khẩu.")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("logs in, persists only the session, clears old query data and replaces the route with dashboard", async () => {
    const result = session();
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(result)));
    const { user, queryClient } = renderLogin();
    await fillForm(user);

    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/auth/login`, expect.objectContaining({
      method: "POST", body: JSON.stringify({ username: "test-admin", password: "test-password" }),
    }));
    expect(getSession()).toEqual(result);
    expect(JSON.parse(localStorage.getItem(AUTH_STORAGE_KEY)!)).toEqual(result);
    expect(queryClient.getQueryData(["previous-private-data"])).toBeUndefined();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).not.toContain("test-password");
  });

  it("shows pending state, disables duplicate submissions and recovers after rejection", async () => {
    let finish!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { finish = resolve; }));
    const { user } = renderLogin();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    const pending = await screen.findByRole("button", { name: "Đang đăng nhập..." });
    expect(pending).toBeDisabled();
    expect(screen.getByLabelText("Tên đăng nhập")).toBeDisabled();
    expect(screen.getByLabelText("Mật khẩu")).toBeDisabled();
    await user.click(pending);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => { finish(new Response("Unauthorized", { status: 401 })); });

    expect(await screen.findByRole("alert")).toHaveTextContent("Đăng nhập không thành công.");
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeEnabled();
    expect(screen.getByLabelText("Mật khẩu")).toHaveValue("");
    expect(getSession()).toBeNull();
  });

  it("uses a generic error for invalid credentials and removes any previous session", async () => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "username does not exist", token: "invalid-token" }), { status: 401 }));
    const { user } = renderLogin();
    await fillForm(user);

    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Đăng nhập không thành công.");
    expect(alert).not.toHaveTextContent("username does not exist");
    expect(getSession()).toBeNull();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    expect(screen.getByLabelText("Mật khẩu")).toHaveValue("");
  });

  it("shows a clear network error and allows retry", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { user } = renderLogin();
    await fillForm(user);

    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Không kết nối được máy chủ.");
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeEnabled();
    expect(getSession()).toBeNull();
  });

  it("handles unavailable authentication without displaying backend error details", async () => {
    fetchMock.mockResolvedValueOnce(new Response("private backend diagnostics", { status: 503 }));
    const { user } = renderLogin();
    await fillForm(user);

    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Dịch vụ đăng nhập tạm thời không khả dụng.");
    expect(alert).not.toHaveTextContent("private backend diagnostics");
  });

  it("explains an expired restored session and accepts a fresh login", async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ ...session(), expires_at: "2020-01-01T00:00:00Z" }));
    restoreSession();
    const { user } = renderLogin();
    expect(screen.getByRole("status")).toHaveTextContent(SESSION_EXPIRED_MESSAGE);
    const fresh = session();
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(fresh)));
    await fillForm(user);

    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeVisible();
    expect(getSession()).toEqual(fresh);
  });

  it("never redirects or persists an already expired response", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ ...session(), expires_at: "2020-01-01T00:00:00Z" })));
    const { user } = renderLogin();
    await fillForm(user);

    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(SESSION_EXPIRED_MESSAGE);
    expect(screen.getByRole("heading", { name: "Đăng nhập quản trị" })).toBeVisible();
    expect(getSession()).toBeNull();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    await waitFor(() => expect(screen.getByLabelText("Mật khẩu")).toHaveValue(""));
  });
});
