import { describe, expect, it } from "vitest";

import { formatDateTime } from "./format";

describe("formatDateTime (D17)", () => {
  it("formats the same instant differently in two locales", () => {
    const iso = "2026-08-12T18:30:00Z";

    const es = formatDateTime(iso, "es-ES");
    const en = formatDateTime(iso, "en-US");

    expect(es).not.toBe(en);
    expect(es).not.toBe("");
    expect(en).not.toBe("");
  });

  it("returns the raw value for an unparseable date instead of throwing", () => {
    expect(formatDateTime("not-a-date", "es-ES")).toBe("not-a-date");
  });
});
