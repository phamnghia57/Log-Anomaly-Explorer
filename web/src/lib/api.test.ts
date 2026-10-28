import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL, ApiError, getCluster, getClusterHistory, getJaegerTraceUrl, listClusters, loginAdmin, searchLogs } from "./api";
import { AUTH_STORAGE_KEY, clearSession, getSession, saveSession, useAuthStore } from "./auth";

describe("query-api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
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

    expect(fetchMock.mock.calls[0][1]).toEqual({ headers: { Authorization: `Bearer ${current.token}` } });
  });

  it("clears a rejected session on 401 without redirecting globally", async () => {
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
