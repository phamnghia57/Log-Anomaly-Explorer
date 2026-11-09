import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AssistantMessage } from "@/lib/api";
import { clearSession, saveSession } from "@/lib/auth";
import { AssistantPanel } from "./AssistantPanel";

const KEY = ["assistant-conversation", "c1"];
const PATH = "/assistant/clusters/c1/conversation";
const TIME = "2026-11-08T00:00:00+00:00";
const history: AssistantMessage[] = [
  { role: "user", content: "Original question 🔎", created_at: TIME },
  { role: "assistant", content: null, created_at: TIME,
    tool_calls: [{ id: "call-1", name: "get_cluster_history", arguments: "{}" }] },
  { role: "tool", content: "[]", name: "get_cluster_history", tool_call_id: "call-1", created_at: TIME },
  { role: "assistant", content: "Original answer", created_at: TIME },
];
const latest: AssistantMessage[] = [
  { role: "user", content: "Latest question", created_at: TIME },
  { role: "assistant", content: "Latest answer", created_at: TIME },
];
const completed = { cluster_id: "c1", messages: [...history, ...latest], revision: "1:7", undo_available: true };
const restored = { cluster_id: "c1", messages: history, revision: "1:8", undo_available: false };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("VT-013 Assistant Undo UI and React Query cache", () => {
  let client: QueryClient;
  let fetchMock: ReturnType<typeof vi.fn>;
  let read: (signal?: AbortSignal | null) => Response | Promise<Response>;
  let undo: () => Response | Promise<Response>;
  let send: (signal?: AbortSignal | null) => Response | Promise<Response>;

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      // Prove the hook overrides a global mutation retry policy.
      mutations: { retry: 2, retryDelay: 0 },
    } });
    read = () => json(completed);
    undo = () => json(restored);
    send = () => json(completed);
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const path = new URL(url).pathname;
      if (path === PATH && !init?.method) return Promise.resolve(read(init?.signal));
      if (path === `${PATH}/undo`) return Promise.resolve(undo());
      if (path === `${PATH}/messages`) return Promise.resolve(send(init?.signal));
      throw new Error(`Unexpected test request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    HTMLElement.prototype.scrollIntoView = vi.fn();
    saveSession({ token: "vt013-component-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() });
  });
  afterEach(() => {
    cleanup();
    client.clear();
    clearSession();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function mount(queryClient = client) {
    return render(<QueryClientProvider client={queryClient}><AssistantPanel clusterId="c1" /></QueryClientProvider>);
  }
  async function loaded() {
    const view = mount();
    await screen.findByText("Latest answer");
    return view;
  }
  function posts(suffix: string) {
    return fetchMock.mock.calls.filter(([url]) => new URL(url).pathname === `${PATH}/${suffix}`);
  }
  const undoButton = () => screen.getByRole("button", { name: "Hoàn tác lượt gửi" });

  it.each([
    [true, "1:0", true], [true, "9223372036854775807:9223372036854775807", true],
    [false, "1:7", false], [true, null, false], [true, "", false], [true, "01:0", false],
    [true, "1:0\n", false], [true, "1:9223372036854775808", false], [true, 7, false],
    ["true", "1:7", false], [undefined, undefined, false],
  ])("F-01 Undo availability flag=%j revision=%j", async (available, revision, enabled) => {
    read = () => json({ ...completed, undo_available: available, revision });
    await loaded();
    if (enabled) expect(undoButton()).toBeEnabled();
    else expect(undoButton()).toBeDisabled();
  });

  it("F-02/03 keyboard Undo uses current authenticated revision and exact server history, without optimistic deletion", async () => {
    const pending = deferred<Response>();
    undo = () => pending.promise;
    await loaded();
    const user = userEvent.setup();
    undoButton().focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(posts("undo")).toHaveLength(1));
    expect(posts("undo")[0][1]).toMatchObject({
      headers: { Authorization: "Bearer vt013-component-token" },
      body: JSON.stringify({ expected_revision: "1:7" }),
    });
    expect(client.getQueryData(KEY)).toEqual(completed);
    expect(screen.getByText("Latest answer")).toBeVisible();
    await act(async () => pending.resolve(json(restored)));
    await waitFor(() => expect(client.getQueryData(KEY)).toEqual(restored));
    expect(screen.queryByText("Latest answer")).not.toBeInTheDocument();
    expect(screen.getByText("Original answer")).toBeVisible();
    expect(screen.getByText("Đang xem xu hướng anomaly score…")).toBeVisible();
    expect(undoButton()).toBeDisabled();
  });

  it("F-03 first-Send Undo accepts the server's persisted empty history", async () => {
    undo = () => json({ ...restored, messages: [] });
    await loaded();
    await userEvent.click(undoButton());
    await waitFor(() => expect(client.getQueryData(KEY)).toEqual({ ...restored, messages: [] }));
    expect(screen.queryByText("Original answer")).not.toBeInTheDocument();
    expect(undoButton()).toBeDisabled();
  });

  it("F-04 HTTP 409 GET-reconciles newer messages, never guesses or retries Undo", async () => {
    const refresh = deferred<Response>();
    const newer = { ...completed, messages: [...completed.messages, { role: "assistant", content: "Another admin's answer", created_at: TIME }], revision: "2:10" };
    await loaded();
    read = () => refresh.promise;
    undo = () => json({ detail: "revision_conflict" }, 409);
    await userEvent.click(undoButton());
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => new URL(url).pathname === PATH)).toHaveLength(2));
    expect(client.getQueryData(KEY)).toEqual(completed);
    expect(undoButton()).toBeDisabled();
    await act(async () => refresh.resolve(json(newer)));
    await screen.findByText("Another admin's answer");
    expect(client.getQueryData(KEY)).toEqual(newer);
    expect(posts("undo")).toHaveLength(1);
    expect(await screen.findByRole("alert")).toBeVisible();
  });

  it.each(["503", "network"])("F-05 %s preserves history until GET confirms the uncertain outcome", async (failure) => {
    const refresh = deferred<Response>();
    await loaded();
    read = () => refresh.promise;
    undo = failure === "503" ? () => json({ error: "storage_unavailable" }, 503) : () => Promise.reject(new TypeError("Failed to fetch"));
    await userEvent.click(undoButton());
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => new URL(url).pathname === PATH)).toHaveLength(2));
    expect(client.getQueryData(KEY)).toEqual(completed);
    expect(screen.getByText("Latest answer")).toBeVisible();
    // The mutation may have committed before its response was lost.
    await act(async () => refresh.resolve(json(restored)));
    await waitFor(() => expect(client.getQueryData(KEY)).toEqual(restored));
    expect(posts("undo")).toHaveLength(1);
    expect(await screen.findByRole("alert")).toBeVisible();
  });

  it("F-05 failed reconciliation retains messages and disables stale Undo until a manual GET succeeds", async () => {
    await loaded();
    undo = () => json({ error: "storage_unavailable" }, 503);
    read = () => json({ error: "storage_unavailable" }, 503);
    await userEvent.click(undoButton());
    await screen.findByRole("alert");
    expect(screen.getByText("Latest answer")).toBeVisible();
    expect(client.getQueryData(KEY)).toEqual(completed);
    expect(undoButton()).toBeDisabled();
    read = () => json(restored);
    await userEvent.click(screen.getByRole("button", { name: "Tải lại hội thoại" }));
    await waitFor(() => expect(client.getQueryData(KEY)).toEqual(restored));
    expect(posts("undo")).toHaveLength(1);
  });

  it("F-06 pending Undo blocks double-clicks, Send and Enter without discarding the draft", async () => {
    const pending = deferred<Response>();
    undo = () => pending.promise;
    await loaded();
    const input = screen.getByPlaceholderText("Hỏi về nguyên nhân, cách sửa…");
    await userEvent.type(input, "Keep this draft");
    await userEvent.dblClick(undoButton());
    expect(undoButton()).toBeDisabled();
    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "Gửi câu hỏi" })).toBeDisabled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(posts("messages")).toHaveLength(0);
    expect(posts("undo")).toHaveLength(1);
    await act(async () => pending.resolve(json(restored)));
    await waitFor(() => expect(input).toBeEnabled());
    expect(input).toHaveValue("Keep this draft");
  });

  it("F-06 pending Send blocks Undo and duplicate Sends", async () => {
    const pending = deferred<Response>();
    send = () => pending.promise;
    await loaded();
    const input = screen.getByPlaceholderText("Hỏi về nguyên nhân, cách sửa…");
    await userEvent.type(input, "Question");
    await userEvent.dblClick(screen.getByRole("button", { name: "Gửi câu hỏi" }));
    expect(undoButton()).toBeDisabled();
    fireEvent.click(undoButton());
    fireEvent.keyDown(input, { key: "Enter" });
    expect(posts("messages")).toHaveLength(1);
    expect(posts("undo")).toHaveLength(0);
    await act(async () => pending.resolve(json(completed)));
  });

  it("F-07 a new QueryClient remount loads the restored history using GET", async () => {
    const view = await loaded();
    await userEvent.click(undoButton());
    await waitFor(() => expect(client.getQueryData(KEY)).toEqual(restored));
    view.unmount();
    client.clear();
    read = () => json(restored);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    mount();
    await screen.findByText("Original answer");
    expect(screen.queryByText("Latest answer")).not.toBeInTheDocument();
    expect(client.getQueryData(KEY)).toEqual(restored);
    expect(undoButton()).toBeDisabled();
  });

  it("F-08 Stop aborts only Send, restores draft, GET-reconciles and never calls Undo", async () => {
    let signal: AbortSignal | null | undefined;
    send = (value) => {
      signal = value;
      return new Promise<Response>((_, reject) => value?.addEventListener("abort", () => reject(new DOMException("Stopped", "AbortError")), { once: true }));
    };
    await loaded();
    const input = screen.getByPlaceholderText("Hỏi về nguyên nhân, cách sửa…");
    await userEvent.type(input, "Stop this wait");
    await userEvent.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));
    await userEvent.click(await screen.findByRole("button", { name: "Dừng" }));
    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(input).toBeEnabled());
    expect(input).toHaveValue("Stop this wait");
    expect(posts("undo")).toHaveLength(0);
    expect(posts("messages")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => new URL(url).pathname === PATH)).toHaveLength(2);
    expect(client.getQueryData(KEY)).toEqual(completed);
    expect(screen.queryByText("AI Assistant chưa trả lời được câu hỏi này.")).not.toBeInTheDocument();
  });

  it("F-09 a late GET started before Undo cannot overwrite its confirmed response", async () => {
    const oldRead = deferred<Response>();
    await loaded();
    read = () => oldRead.promise;
    let refresh!: Promise<void>;
    await act(async () => { refresh = client.refetchQueries({ queryKey: KEY }); });
    // Starting via the mutation hook's public API is covered by the UI action;
    // wait until the background query settles or is cancelled by that action.
    await userEvent.click(undoButton());
    await act(async () => oldRead.resolve(json(completed)));
    await refresh;
    await waitFor(() => expect(client.getQueryData(KEY)).toEqual(restored));
    expect(screen.queryByText("Latest answer")).not.toBeInTheDocument();
  });

  it("F-10 logout during a confirmed Undo cache update cannot repopulate cleared private state", async () => {
    const pendingUndo = deferred<Response>();
    const background = deferred<Response>();
    undo = () => pendingUndo.promise;
    await loaded();
    await userEvent.click(undoButton());
    // A focus refresh can begin while the HTTP mutation is pending. Log out
    // when that read is cancelled before the successful mutation cache write.
    read = (signal) => {
      signal?.addEventListener("abort", () => { clearSession(); client.clear(); }, { once: true });
      return background.promise;
    };
    await act(async () => { void client.refetchQueries({ queryKey: KEY }); });
    await act(async () => pendingUndo.resolve(json(restored)));
    await waitFor(() => expect(client.isMutating()).toBe(0));
    expect(client.getQueryData(KEY)).toBeUndefined();
    expect(posts("undo")).toHaveLength(1);
    await act(async () => background.resolve(json(completed)));
    expect(client.getQueryData(KEY)).toBeUndefined();
  });
});
