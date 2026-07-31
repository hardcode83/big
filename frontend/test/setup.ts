import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// This jsdom build does not ship the Web Storage API; provide a minimal
// in-memory localStorage so persistence-backed code (e.g. the shell UI store)
// is testable.
//
// Feature-detect the METHODS, not the object. Node 22+ exposes a global
// `localStorage` of its own (Web Storage, backed by `--localstorage-file`), and the
// jsdom window picks it up — so on Node 25 the old truthiness check saw something
// there, skipped the polyfill, and left `window.localStorage.clear` undefined,
// which took down 27 tests across four shell files. Truthiness was never the
// question; whether the thing behaves like Storage is.
const storageIsUsable =
  typeof window !== "undefined" &&
  typeof window.localStorage?.clear === "function" &&
  typeof window.localStorage?.getItem === "function" &&
  typeof window.localStorage?.setItem === "function";

if (typeof window !== "undefined" && !storageIsUsable) {
  const store = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
      setItem: (key: string, value: string) => {
        store.set(key, String(value));
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
      clear: () => {
        store.clear();
      },
      key: (index: number) => Array.from(store.keys())[index] ?? null,
      get length() {
        return store.size;
      },
    },
  });
}

// Unmount React trees and reset jsdom between tests so state never leaks.
afterEach(() => {
  cleanup();
});
