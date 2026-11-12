import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  API_BASE_URL,
  ApiError,
  getAssistantConversation,
  getCluster,
  getClusterHistory,
  getJaegerTraceUrl,
  HEALTH_ENDPOINTS,
  listClusters,
  loginAdmin,
  searchLogs,
  searchAggregations,
  getSystemHealth,
  sendAssistantMessage,
  streamAssistantMessage,
  updateIncident,
  type AssistantStreamEvent,
} from "./api";
import { AUTH_STORAGE_KEY, clearSession, getSession, saveSession, SessionExpiredError, useAuthStore } from "./auth";

describe("query-api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    saveSession({ token: "test-token", session_id: "test-session", expires_at: new Date(Date.now() + 3_600_000).toISOString() });
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
    expect(calledUrl.pathname).toBe("/api/search");
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

  it("searchAggregations: sends level and time range", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ histogram: [], levels: [], services: [] })));
    await searchAggregations({ level: "ERROR", from: "2026-10-01" });
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/api/search/aggregations");
    expect(url.searchParams.get("level")).toBe("ERROR");
  });

  it("getSystemHealth: handles down service without losing others", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" })));
    fetchMock.mockRejectedValueOnce(new Error("connection failed"));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ status: "degraded" }), { status: 503 }));
    // Cac endpoint con lai (danh sach co the dai them khi bo sung service moi)
    // deu tra ok - test nay chi kiem "1 service chet khong lam mat ket qua cua
    // cac service khac", khong phu thuoc vao SO LUONG endpoint.
    for (let i = 3; i < HEALTH_ENDPOINTS.length; i += 1) {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" })));
    }

    const health = await getSystemHealth();

    expect(health).toHaveLength(HEALTH_ENDPOINTS.length);
    expect(health.slice(0, 3).map((entry) => entry.ok)).toEqual([true, false, false]);
    expect(health[1].status).toBe("unreachable");
    expect(health[2].status).toBe("HTTP 503");
    expect(health.slice(3).every((entry) => entry.ok)).toBe(true);
  });

  it("getSystemHealth: co kiem tra ca AI Assistant", async () => {
    // /assistant/health luon tra HTTP 200 kem `status` co y nghia (vd. het
    // quota Azure OpenAI) - khac cac /health khac co the tra 503.
    expect(HEALTH_ENDPOINTS.map((entry) => entry.name)).toContain("AI Assistant");
    const assistant = HEALTH_ENDPOINTS.find((entry) => entry.name === "AI Assistant");
    expect(assistant?.url).toBe(`${API_BASE_URL}/assistant/health`);
  });

  it("listClusters: loc theo status dung tham so", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ total: 0, clusters: [] }), { status: 200 }),
    );

    await listClusters({ status: "alerted" });

    const calledUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(calledUrl.pathname).toBe("/api/clusters");
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
    expect(calledUrl.pathname).toBe("/api/clusters/c1");
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
    expect(calledUrl.pathname).toBe("/api/clusters/c1/history");
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
    expect(calledUrl.pathname).toBe("/api/assistant/clusters/c1/conversation");
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
    expect(new URL(url as string).pathname).toBe("/api/assistant/clusters/c1/conversation/messages");
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ message: "Loi nay la gi?" });
    expect(body).toEqual(conversation);
  });

  it("streamAssistantMessage: cung endpoint, doc SSE va ghep lai cau tra loi", async () => {
    const conversation = {
      cluster_id: "c1",
      messages: [
        { role: "user", content: "Loi nay la gi?", created_at: "2026-10-29T00:00:00Z" },
        { role: "assistant", content: "Nguyen nhan: X", created_at: "2026-10-29T00:00:01Z" },
      ],
    };
    // Mot event bi cat giua 2 chunk - reader phai gom lai dung, khong mat chu.
    const frames = [
      'data: {"delta": "Nguyen "}\n\ndata: {"to',
      'ol": "search_related_logs"}\n\n',
      'data: {"delta": "nhan: X"}\n\n',
      `data: ${JSON.stringify({ conversation })}\n\n`,
    ];
    fetchMock.mockResolvedValueOnce(new Response(new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder();
        for (const frame of frames) controller.enqueue(encoder.encode(frame));
        controller.close();
      },
    }), { status: 200, headers: { "Content-Type": "text/event-stream" } }));

    const events: AssistantStreamEvent[] = [];
    const body = await streamAssistantMessage("c1", "Loi nay la gi?", (event) => events.push(event));

    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(url as string).pathname).toBe("/api/assistant/clusters/c1/conversation/messages");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).headers).toMatchObject({ Accept: "text/event-stream" });
    expect(events).toEqual([
      { delta: "Nguyen " }, { tool: "search_related_logs" }, { delta: "nhan: X" },
    ]);
    expect(body).toEqual(conversation);
  });

  it("streamAssistantMessage: event error giua stream thanh ApiError", async () => {
    fetchMock.mockResolvedValueOnce(new Response(
      'data: {"delta": "dang tra loi"}\n\ndata: {"error": "AI Assistant loi: PermissionError"}\n\n',
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    ));

    const error = await streamAssistantMessage("c1", "hi", () => {}).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toContain("PermissionError");
  });

  it("streamAssistantMessage: stream ngat truoc event conversation thi bao loi", async () => {
    fetchMock.mockResolvedValueOnce(new Response(
      'data: {"delta": "dang tra loi roi mat ket noi"}\n\n',
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    ));

    await expect(streamAssistantMessage("c1", "hi", () => {})).rejects.toBeInstanceOf(ApiError);
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
  const session = () => ({ token: "test-token", session_id: "test-session", expires_at: new Date(Date.now() + 3_600_000).toISOString() });

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
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Protection": "1" },
      body: JSON.stringify({ username: "test-admin", password: "test-password" }), cache: "no-store", credentials: "same-origin", redirect: "error",
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
    clearSession();
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

    expect(fetchMock.mock.calls[0][1].headers).toEqual({ "Content-Type": "application/json", "X-CSRF-Protection": "1" });
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

  it("does not fetch business data when anonymous and refreshes expired access first", async () => {
    await expect(searchLogs({})).rejects.toMatchObject({ status: 401 });
    const old = session(); saveSession(old);
    vi.spyOn(Date, "now").mockReturnValue(Date.parse(old.expires_at) + 1);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
    await expect(listClusters({})).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/auth/refresh");
    vi.restoreAllMocks();
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

  it("retries a POST once only after an explicit expired-access rejection", async () => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401, headers: { "X-Auth-Reason": "access_expired" } }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ ...session(), token: "refreshed-token" })));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ cluster_id: "c1", messages: [] })));
    await sendAssistantMessage("c1", "Investigate");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toContain("/auth/refresh");
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe("Bearer refreshed-token");
  });

  it.each([true, false])("retries an incident update only when refresh keeps the same session (%s)", async (sameSession) => {
    const current = session();
    saveSession(current);
    const refreshed = { ...current, token: "refreshed-token", session_id: sameSession ? current.session_id : "other-admin" };
    const change = { action: "acknowledge", episode_id: "c1:1" } as const;
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 401, headers: { "X-Auth-Reason": "access_expired" } }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(refreshed)));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ episode_id: change.episode_id, status: "acknowledged" })));

    const request = updateIncident("c1", change);
    if (sameSession) {
      await expect(request).resolves.toMatchObject({ status: "acknowledged" });
      expect(fetchMock).toHaveBeenCalledTimes(3);
      expect(fetchMock.mock.calls[2][1]).toMatchObject({
        method: "PATCH", headers: { Authorization: "Bearer refreshed-token" }, body: JSON.stringify(change),
      });
    } else {
      await expect(request).rejects.toBeInstanceOf(SessionExpiredError);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(getSession()).toBeNull();
    }
    expect(fetchMock.mock.calls[1][0]).toContain("/auth/refresh");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ expected_session_id: current.session_id });
  });

  it.each([503, 500])("does not replay a business POST on HTTP %s", async (status) => {
    saveSession(session());
    fetchMock.mockResolvedValueOnce(new Response("Unavailable", { status }));
    await expect(sendAssistantMessage("c1", "Investigate")).rejects.toMatchObject({ status });
    expect(fetchMock).toHaveBeenCalledTimes(1);
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
