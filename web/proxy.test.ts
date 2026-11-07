import { afterEach, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

it("routes API before the SPA fallback using the deployment backend origin", async () => {
  vi.stubEnv("API_PROXY_TARGET", "https://backend.example/");
  const { config } = await import("./vercel");
  expect(config.rewrites).toEqual([
    { source: "/api/:path*", destination: "https://backend.example/:path*" },
    { source: "/(.*)", destination: "/index.html" },
  ]);
});

it.each(["", "http://backend.example", "https://user:secret@backend.example", "https://backend.example/path"])(
  "rejects a missing or unsafe production proxy target", async (target) => {
    vi.stubEnv("API_PROXY_TARGET", target);
    await expect(import("./vercel")).rejects.toThrow("API_PROXY_TARGET must be an HTTPS backend origin");
  },
);
