import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, getCluster, getClusterHistory, getJaegerTraceUrl, listClusters, searchLogs } from "./api";

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
