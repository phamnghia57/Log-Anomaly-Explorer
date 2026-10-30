import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  API_BASE_URL,
  ApiError,
  getAssistantConversation,
  getCluster,
  getClusterHistory,
  getJaegerTraceUrl,
  listClusters,
  loginAdmin,
  searchLogs,
  sendAssistantMessage,
} from "./api";
import { AUTH_STORAGE_KEY, clearSession, getSession, saveSession, useAuthStore } from "./auth";

describe("query-api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    saveSession({ token: "test-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    clearSession();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("searchLogs: goi dung endpoint /search voi cac param duoc truyen", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ total: 0, results: [] }), { status: 200 }),
    );

    await searchLogs({ service: "demo-web", trace_id: "abc123" });

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.pathname).toBe("/search");
    expect(calledUrl.searchParams.get("service")).toBe("demo-web");
    expect(calledUrl.searchParams.get("trace_id")).toBe("abc123");
  });

  it("searchLogs: khong gui param rong/undefined len query string", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ total: 0, results: [] }), { status: 200 }),
    );

    await searchLogs({ service: "", q: undefined });

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.searchParams.has("service")).toBe(false);
    expect(calledUrl.searchParams.has("q")).toBe(false);
  });

  it("listClusters: loc theo status dung tham so", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ total: 0, clusters: [] }), { status: 200 }),
    );

    await listClusters({ status: "alerted" });

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.pathname).toBe("/clusters");
    expect(calledUrl.searchParams.get("status")).toBe("alerted");
  });

  it("getCluster: nem ApiError voi status 404 khi khong tim thay cum", async () => {
    fetchMock.mockResolvedValueOnce(new Response("cluster not found", { status: 404 }));

    const error = await getCluster("does-not-exist").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404 });
  });

  it("getCluster: gui logs_limit khi can tai them log", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ cluster_id: "c1", logs: [], logs_total: 250 }), { status: 200 }),
    );

    await getCluster("c1", { logsLimit: 200 });

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.pathname).toBe("/clusters/c1");
    expect(calledUrl.searchParams.get("logs_limit")).toBe("200");
  });

  it("getCluster: khong gui logs_limit/logs_offset khi khong truyen", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ cluster_id: "c1", logs: [] }), { status: 200 }),
    );

    await getCluster("c1");

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.searchParams.has("logs_limit")).toBe(false);
    expect(calledUrl.searchParams.has("logs_offset")).toBe(false);
  });

  it("getClusterHistory: goi dung endpoint /clusters/{id}/history", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ cluster_id: "c1", points: [] }), { status: 200 }),
    );

    const body = await getClusterHistory("c1");

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.pathname).toBe("/clusters/c1/history");
    expect(body).toEqual({ cluster_id: "c1", points: [] });
  });

  it("nem ApiError (status 0) khi fetch that bai hoan toan (vd. backend sap/mixed content)", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(searchLogs({})).rejects.toMatchObject({ status: 0 });
  });

  it("getAssistantConversation: goi dung endpoint, tra ve messages rong khi chua hoi lan nao", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ cluster_id: "c1", messages: [] }), { status: 200 }),
    );

    const body = await getAssistantConversation("c1");

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.pathname).toBe("/assistant/clusters/c1/conversation");
    expect(body).toEqual({ cluster_id: "c1", messages: [] });
  });

  it("sendAssistantMessage: POST dung body JSON, tra ve toan bo hoi thoai moi", async () => {
    const conversation = {
      cluster_id: "c1",
      messages: [
        { role: "user", content: "Loi nay la gi?", created_at: "2026-10-29T00:00:00Z" },
        { role: "assistant", content: "De xuat: ...", created_at: "2026-10-29T00:00:01Z" },
      ],
    };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(conversation), { status: 200 }));

    const body = await sendAssistantMessage("c1", "Loi nay la gi?");

    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(url as string).pathname).toBe("/assistant/clusters/c1/conversation/messages");
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ message: "Loi nay la gi?" });
    expect(body).toEqual(conversation);
  });

  it("sendAssistantMessage: nem ApiError voi status 503 khi thieu AZURE_OPENAI_API_KEY", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("AI Assistant chua duoc cau hinh", { status: 503 }),
    );

    const error = await sendAssistantMessage("c1", "hi").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 503 });
  });
});

describe("admin login and authenticated API requests", () => {
  const fetchMock = vi.fn();
  const session = () => ({ token: "test-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() });

  beforeEach(() => {
    clearSession();
    localStorage.clear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    clearSession();
    localStorage.clear();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("posts JSON credentials to the configured API base URL without putting them in a URL", async () => {
    const result = session();
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(result)));

    await expect(loginAdmin("test-admin", "test-password")).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "test-admin", password: "test-password" }), cache: "no-store",
    });
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it.each([401, 403])("uses a generic login error for HTTP %i and never saves its body", async (status) => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "username does not exist", token: "invalid" }), { status }));

    const error = await loginAdmin("test-admin", "test-password").catch((cause) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(status);
    expect(error.message).not.toContain("username does not exist");
    expect(getSession()).toBeNull();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it("reports login network failures without exposing request details", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(loginAdmin("test-admin", "test-password")).rejects.toMatchObject({ status: 0 });
  });

  it.each(["not-json", JSON.stringify({ token: "invalid" }), JSON.stringify({ token: "", expires_at: "invalid" })])(
    "rejects a malformed successful response", async (body) => {
      fetchMock.mockResolvedValueOnce(new Response(body));

      await expect(loginAdmin("test-admin", "test-password")).rejects.toMatchObject({ status: 502 });
      expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    },
  );

  it("attaches the current token to shared query requests", async () => {
    const current = session();
    saveSession(current);
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ total: 0, results: [] })));

    await searchLogs({});

    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { Authorization: `Bearer ${current.token}` } });
  });

  it("clears a rejected session on 401 so the router can redirect", async () => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response("Unauthorized", { status: 401 }));

    await expect(searchLogs({})).rejects.toMatchObject({ status: 401 });

    expect(getSession()).toBeNull();
    expect(useAuthStore.getState().status).toBe("expired");
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it("does not let a late 401 from an old request erase a newer login", async () => {
    saveSession(session());
    let finish!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { finish = resolve; }));
    const request = searchLogs({}).catch((cause) => cause);
    const newer = { ...session(), token: "newer-test-token" };
    saveSession(newer);

    finish(new Response("Unauthorized", { status: 401 }));
    await request;

    expect(getSession()).toEqual(newer);
  });

  it.each([
    ["/search", () => searchLogs({})],
    ["/clusters", () => listClusters({})],
    ["/clusters/c1", () => getCluster("c1")],
    ["/clusters/c1/history", () => getClusterHistory("c1")],
    ["/assistant/clusters/c1/conversation", () => getAssistantConversation("c1")],
    ["/assistant/clusters/c1/conversation/messages", () => sendAssistantMessage("c1", "Investigate")],
  ])("sends Bearer auth only to the configured protected endpoint %s", async (path, request) => {
    const current = session();
    saveSession(current);
    fetchMock.mockResolvedValueOnce(new Response("{}"));

    await request();

    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}${path}`, expect.objectContaining({
      headers: expect.objectContaining({ Authorization: `Bearer ${current.token}` }),
      cache: "no-store", credentials: "omit", redirect: "error",
    }));
  });

  it("never attaches an existing token to the public login request", async () => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(session())));

    await loginAdmin("test-admin", "test-password");

    expect(fetchMock.mock.calls[0][1].headers).toEqual({ "Content-Type": "application/json" });
  });

  it.each([
    () => getAssistantConversation("c1"),
    () => sendAssistantMessage("c1", "Investigate"),
  ])("clears a rejected Assistant session through the shared authenticated client", async (request) => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response("Unauthorized", { status: 401 }));

    await expect(request()).rejects.toMatchObject({ status: 401 });

    expect(getSession()).toBeNull();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    expect(useAuthStore.getState().status).toBe("expired");
  });

  it("does not fetch when anonymous or expired", async () => {
    await expect(searchLogs({})).rejects.toMatchObject({ status: 401 });
    saveSession(session());
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 3_600_001);
    try {
      await expect(listClusters({})).rejects.toMatchObject({ status: 401 });
      expect(getSession()).toBeNull();
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      vi.restoreAllMocks();
    }
  });

  it.each(["..", "."])("rejects cluster IDs that normalize outside the protected endpoint: %s", async (id) => {
    saveSession(session());

    await expect(getCluster(id)).rejects.toMatchObject({ status: 400 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps URL-like cluster IDs on the configured API, never the external service", async () => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response("{}"));

    await getCluster("https://external.example/collect");

    const url = new URL(fetchMock.mock.calls[0][0]);
    expect(url.origin).toBe(new URL(API_BASE_URL).origin);
    expect(url.pathname).toContain("/clusters/https%3A%2F%2Fexternal.example%2Fcollect");
  });

  it("does not return data from a request that finishes after logout", async () => {
    saveSession(session());
    let finish!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { finish = resolve; }));
    const request = searchLogs({});
    clearSession();

    finish(new Response(JSON.stringify({ results: ["private"] })));

    await expect(request).rejects.toMatchObject({ status: 401 });
  });

  it("passes cancellation through to fetch without changing AbortError to a network error", async () => {
    saveSession(session());
    const controller = new AbortController();
    const aborted = new DOMException("Aborted", "AbortError");
    fetchMock.mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(aborted));
    }));
    const request = searchLogs({}, controller.signal);

    controller.abort();

    await expect(request).rejects.toBe(aborted);
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });
});

describe("getJaegerTraceUrl", () => {
  it("tra ve null khi VITE_JAEGER_URL khong duoc cau hinh (mac dinh luc test)", () => {
    // Khong co .env.local/.env.test trong repo nen VITE_JAEGER_URL luc test la
    // undefined - dung lai module da import san (khong can stub).
    expect(getJaegerTraceUrl("abc123")).toBeNull();
  });

  it("tra ve null khi trace_id rong, du da cau hinh JAEGER_URL", async () => {
    vi.stubEnv("VITE_JAEGER_URL", "http://localhost:16686");
    vi.resetModules();
    const { getJaegerTraceUrl: getUrl } = await import("./api");

    expect(getUrl("")).toBeNull();
  });

  it("ghep dung duong dan /trace/{id} khi da cau hinh JAEGER_URL", async () => {
    vi.stubEnv("VITE_JAEGER_URL", "http://localhost:16686");
    vi.resetModules();
    const { getJaegerTraceUrl: getUrl } = await import("./api");

    expect(getUrl("0af7651916cd43dd8448eb211c80319c")).toBe(
      "http://localhost:16686/trace/0af7651916cd43dd8448eb211c80319c",
    );
  });

  it("bo dau / cuoi cua VITE_JAEGER_URL neu co, tranh duong dan bi lap dau //", async () => {
    vi.stubEnv("VITE_JAEGER_URL", "http://localhost:16686/");
    vi.resetModules();
    const { getJaegerTraceUrl: getUrl } = await import("./api");

    expect(getUrl("abc123")).toBe("http://localhost:16686/trace/abc123");
  });
});
