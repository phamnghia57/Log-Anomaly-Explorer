import { describe, expect, it } from "vitest";
import { safeReturnTo } from "./auth-navigation";

describe("safe login return destination", () => {
  it.each(["/", "/search?trace_id=abc#results", "/clusters/c1?logs_limit=200"])("preserves %s", (path) => {
    expect(safeReturnTo(path)).toBe(path);
  });

  it.each([
    undefined, null, 123, {}, "https://external.example", "//external.example", "/\\external.example",
    "javascript:alert(1)", "/login", "/login?from=/login", "/other-service", "/search\n", "/search\t",
    "/%2f%2fexternal.example", "/clusters/../../login", "/clusters/a/b",
  ])("falls back to dashboard for unsafe or unknown destinations: %s", (path) => {
    expect(safeReturnTo(path)).toBe("/");
  });
});
