// @vitest-environment node
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { getTransformedRoutes } from "@vercel/routing-utils";
import { build } from "esbuild";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

const webRoot = fileURLToPath(new URL(".", import.meta.url));
let compiledConfigScript: string;

beforeAll(async () => {
  // Vercel bundles the config with esbuild, executes it in a child process,
  // then serializes it to JSON. An in-process TS import alone misses this step.
  const result = await build({
    stdin: {
      contents: 'import config from "./vercel.ts"; console.log(JSON.stringify(config));',
      resolveDir: webRoot,
      sourcefile: "vercel-config-loader.ts",
    },
    bundle: true,
    platform: "node",
    format: "esm",
    packages: "external",
    target: "node20",
    write: false,
  });
  compiledConfigScript = result.outputFiles[0].text;
});

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

it("routes API before the SPA fallback using the deployment backend origin", async () => {
  vi.stubEnv("API_PROXY_TARGET", "https://backend.example/");
  const { default: config } = await import("./vercel");
  expect(config.rewrites).toEqual([
    { source: "/api/:path*", destination: "https://backend.example/:path*" },
    { source: "/(.*)", destination: "/index.html" },
  ]);
});

it.each(["https://backend.example", "https://backend.example/"])(
  "preserves destinations and headers through Vercel-style config compilation: %s", (target) => {
    const config = JSON.parse(execFileSync(process.execPath,
      ["--input-type=module", "--eval", compiledConfigScript], {
        cwd: webRoot,
        env: { ...process.env, API_PROXY_TARGET: target },
        encoding: "utf8",
        timeout: 10_000,
      }));
    expect(config.rewrites).toEqual([
      { source: "/api/:path*", destination: "https://backend.example/:path*" },
      { source: "/(.*)", destination: "/index.html" },
    ]);
    expect(config.headers).toEqual([
      { source: "/api/:path*", headers: [{ key: "Cache-Control", value: "no-store" }] },
    ]);
    const { error, routes } = getTransformedRoutes(config);
    expect(error).toBeNull();
    const apiRoute = routes?.find((route) => "dest" in route && route.dest?.startsWith("https://backend.example"));
    expect(apiRoute).toBeDefined();
    if (apiRoute && "src" in apiRoute && "dest" in apiRoute) {
      const match = new RegExp(apiRoute.src).exec("/api/auth/refresh");
      expect(match).not.toBeNull();
      expect(apiRoute.dest?.replace(/\$(\d+)/g, (_, group) => match?.[Number(group)] ?? ""))
        .toBe("https://backend.example/auth/refresh");
    }
  },
);

it.each(["", "http://backend.example", "https://user:secret@backend.example", "https://backend.example/path"])(
  "rejects a missing or unsafe production proxy target", async (target) => {
    vi.stubEnv("API_PROXY_TARGET", target);
    await expect(import("./vercel")).rejects.toThrow("API_PROXY_TARGET must be an HTTPS backend origin");
  },
);
