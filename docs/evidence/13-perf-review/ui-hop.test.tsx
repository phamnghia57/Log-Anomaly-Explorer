import { writeFileSync } from "node:fs";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { clearSession, saveSession } from "@/lib/auth";
import App from "./App";

afterEach(() => {
  cleanup();
  clearSession();
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function measure(offsetMs: number) {
  vi.useFakeTimers();
  saveSession({ token: "t", session_id: "s", expires_at: new Date(Date.now() + 3_600_000).toISOString() });
  let heartbeat = "2026-11-25T00:00:10Z";
  const fetchMock = vi.fn((url: string) => Promise.resolve(url.endsWith("/clustering/health")
    ? new Response(JSON.stringify({ status: "ok", reason: null, last_processed_at: heartbeat }))
    : new Response(JSON.stringify({ total: 0, clusters: [] }))));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: 1, retryDelay: 0, staleTime: 10_000 } } });
  render(<QueryClientProvider client={client}><MemoryRouter><TooltipProvider><App /></TooltipProvider></MemoryRouter></QueryClientProvider>);
  const clusterCalls = () => fetchMock.mock.calls.filter(([url]) => new URL(url, "http://x").pathname.endsWith("/clusters")).length;
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  await act(async () => { await vi.advanceTimersByTimeAsync(offsetMs); });
  const before = clusterCalls();
  heartbeat = "2026-11-25T00:01:10Z";
  let waited = 0;
  while (clusterCalls() === before && waited < 60_000) {
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    waited += 100;
  }
  client.clear();
  return waited;
}

it("measures heartbeat-to-refetch delay over one 30 s period", async () => {
  const delays: number[] = [];
  for (let offset = 0; offset < 30_000; offset += 700) delays.push(await measure(offset));
  const sorted = [...delays].sort((a, b) => a - b);
  const result = {
    samples: delays.length, offsets_ms: "0..29400 step 700", resolution_ms: 100,
    min_ms: sorted[0], median_ms: sorted[Math.floor(sorted.length / 2)], max_ms: sorted[sorted.length - 1],
    mean_ms: Math.round(delays.reduce((a, b) => a + b, 0) / delays.length), delays_ms: delays,
  };
  writeFileSync(process.env.UI_HOP_OUT ?? "ui-hop.json", `${JSON.stringify(result)}\n`);
  expect(delays).toHaveLength(43);
}, 120_000);
