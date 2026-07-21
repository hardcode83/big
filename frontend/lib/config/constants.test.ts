import { describe, expect, it } from "vitest";

import { DEFAULT_LOCALE, isLocale } from "@/lib/config/constants";

describe("isLocale", () => {
  it("accepts supported locales", () => {
    expect(isLocale("es")).toBe(true);
    expect(isLocale("en")).toBe(true);
  });

  it("rejects unsupported or non-string values", () => {
    for (const value of ["fr", "ES", "", null, undefined, 123, {}]) {
      expect(isLocale(value)).toBe(false);
    }
  });

  it("defaults the product locale to es", () => {
    expect(DEFAULT_LOCALE).toBe("es");
  });
});
