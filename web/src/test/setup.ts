import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

// jsdom has no Web Locks. Match exclusive, cross-operation serialization in unit tests.
beforeEach(() => {
  let queue = Promise.resolve();
  Object.defineProperty(navigator, "locks", { configurable: true, value: {
    request: (_name: string, callback: () => Promise<unknown>) => {
      const result = queue.then(callback);
      queue = result.then(() => undefined, () => undefined);
      return result;
    },
  } });
});
