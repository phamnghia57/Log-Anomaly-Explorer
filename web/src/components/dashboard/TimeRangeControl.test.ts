import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sinceFromRange, TIME_RANGES } from "./TimeRangeControl";

describe("sinceFromRange", () => {
  const NOW = new Date("2026-10-29T12:00:00.000Z");

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("tra ve thoi diem lui dung so giay cua moi range", () => {
    expect(sinceFromRange("15m")).toBe("2026-10-29T11:45:00.000Z");
    expect(sinceFromRange("1h")).toBe("2026-10-29T11:00:00.000Z");
    expect(sinceFromRange("24h")).toBe("2026-10-28T12:00:00.000Z");
    expect(sinceFromRange("7d")).toBe("2026-10-22T12:00:00.000Z");
  });

  it("moi key trong TIME_RANGES deu sinh duoc ISO string hop le", () => {
    for (const key of Object.keys(TIME_RANGES) as (keyof typeof TIME_RANGES)[]) {
      expect(() => new Date(sinceFromRange(key)).toISOString()).not.toThrow();
    }
  });
});
