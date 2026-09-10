import { afterEach, describe, expect, it } from "vitest";

import { DEFAULT_LOCALE } from "@/lib/config/constants";
import { getActiveLocale, setActiveLocale } from "./active-locale";

describe("active-locale (security review, round 12)", () => {
  afterEach(() => {
    setActiveLocale(DEFAULT_LOCALE);
  });

  it("publishes normally when window is defined (every real browser, and this test's own jsdom environment)", () => {
    setActiveLocale("en");
    expect(getActiveLocale()).toBe("en");
  });

  it("is a no-op when window is undefined, so a concurrent SSR render in the same Node process cannot overwrite another request's published locale", () => {
    const originalWindow = globalThis.window;
    // @ts-expect-error simulating the one environment this module must not
    // publish in: a Node process with no browser globals (SSR).
    delete globalThis.window;

    try {
      setActiveLocale("en");
      expect(getActiveLocale()).toBe(DEFAULT_LOCALE);
    } finally {
      globalThis.window = originalWindow;
    }
  });
});
