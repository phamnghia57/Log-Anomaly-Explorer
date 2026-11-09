import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { clearSession, saveSession } from "./auth";

type Undo = (clusterId: string, revision: string) => Promise<api.AssistantConversation>;

// The RED suite must execute assertions even before the new export exists.
function undo(): Undo {
  const request = Reflect.get(api, "undoAssistantSend");
  expect(request).toBeTypeOf("function");
  return request as Undo;
}

describe("VT-013 Undo API contract", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    saveSession({ token: "vt013-test-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    clearSession();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("F-02 sends the current opaque revision and existing Bearer header to encoded cluster path", async () => {
    const restored = { cluster_id: "cluster/one", messages: [], revision: "2:8", undo_available: false };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(restored)));
    await expect(undo()("cluster/one", "2:7")).resolves.toEqual(restored);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      `${api.API_BASE_URL}/assistant/clusters/cluster%2Fone/conversation/undo`,
      expect.objectContaining({
        method: "POST", body: JSON.stringify({ expected_revision: "2:7" }),
        headers: { Authorization: "Bearer vt013-test-token", "Content-Type": "application/json" },
        credentials: "omit", redirect: "error", cache: "no-store",
      }),
    );
  });

  it.each(["1:0", "9223372036854775807:9223372036854775807"])("F-01 accepts valid revision boundary %s unchanged", async (revision) => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ cluster_id: "c1", messages: [], revision: "1:9", undo_available: false })));
    await undo()("c1", revision);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ expected_revision: revision });
  });

  it.each(["", "0:0", "01:0", "1:00", "1:-1", "1:0\n", "１:0", "1:9223372036854775808"])(
    "F-01 rejects invalid revision %j before a request", async (revision) => {
      await expect(undo()("c1", revision)).rejects.toMatchObject({ status: 422 });
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it.each([409, 503])("F-04/05 preserves HTTP %i as an error, never a default conversation", async (status) => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "rejected" }), { status }));
    await expect(undo()("c1", "1:0")).rejects.toMatchObject({ status });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("F-05 propagates a network failure", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(undo()("c1", "1:0")).rejects.toMatchObject({ status: 0 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("F-02 does not fetch without a valid admin session", async () => {
    clearSession();
    await expect(undo()("c1", "1:0")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
