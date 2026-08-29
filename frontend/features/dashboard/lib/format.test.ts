import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime } from "./format";

const ISO = "2026-08-20T09:30:00Z";

describe("formatDateTime / formatDate — valid input", () => {
  it("formats a well-formed ISO timestamp in the given locale", () => {
    const es = formatDateTime(ISO, "es");
    const en = formatDateTime(ISO, "en");
    expect(es).toMatch(/2026/);
    expect(en).toMatch(/2026/);
    expect(es).not.toBe(ISO);
    expect(en).not.toBe(ISO);
  });

  it("formats the date-only variant without a time component", () => {
    expect(formatDate(ISO, "en")).toMatch(/2026/);
  });
});

/**
 * A malformed `due_since` reaches the card whenever the backend and the
 * frontend disagree (deploy skew, a partial migration). Before the guard,
 * `Intl.DateTimeFormat.format` threw `RangeError: Invalid time value` inside
 * the render loop and took the whole property card down with it.
 */
describe("formatDateTime — malformed input never throws (R1.2)", () => {
  it.each([
    ["empty string", ""],
    ["whitespace", "   "],
    ["not a date", "not-an-iso"],
    ["truncated", "2026-13-45T99:99:99Z"],
    ["a sentence", "el martes que viene"],
  ])("returns the raw value for %s instead of throwing", (_label, input) => {
    expect(() => formatDateTime(input, "es")).not.toThrow();
    expect(formatDateTime(input, "es")).toBe(input);
  });

  it("does not silently render the Unix epoch for a null-ish value", () => {
    // `new Date(null)` is 1970-01-01 — a plausible-looking date that is a lie.
    const out = formatDateTime(null as unknown as string, "es");
    expect(out).not.toMatch(/1970/);
    expect(out).toBe("");
  });

  it("applies the same guard to formatDate", () => {
    expect(() => formatDate("not-an-iso", "en")).not.toThrow();
    expect(formatDate("not-an-iso", "en")).toBe("not-an-iso");
    expect(formatDate(null as unknown as string, "en")).toBe("");
  });
});
