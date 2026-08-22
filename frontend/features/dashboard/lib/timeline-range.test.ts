import { describe, expect, it } from "vitest";

import { endOfDayIso, isInverseRange, startOfDayIso } from "./timeline-range";

/**
 * The assertions read the results back through LOCAL getters instead of comparing
 * literal strings, so the suite proves the intended property — "the start of the
 * day the operator picked, in her own zone" — in whatever zone the runner happens
 * to use, rather than only passing under UTC.
 */
describe("timeline range (R4.2, R4.3, R4.4)", () => {
  it("startOfDayIso is the first instant of the chosen local day", () => {
    const instant = new Date(startOfDayIso("2026-08-05")!);

    expect(instant.getFullYear()).toBe(2026);
    expect(instant.getMonth()).toBe(7);
    expect(instant.getDate()).toBe(5);
    expect(instant.getHours()).toBe(0);
    expect(instant.getMinutes()).toBe(0);
    expect(instant.getSeconds()).toBe(0);
    expect(instant.getMilliseconds()).toBe(0);
  });

  it("endOfDayIso is the last instant of the chosen local day (inclusive `to`)", () => {
    const instant = new Date(endOfDayIso("2026-08-05")!);

    expect(instant.getDate()).toBe(5);
    expect(instant.getHours()).toBe(23);
    expect(instant.getMinutes()).toBe(59);
    expect(instant.getSeconds()).toBe(59);
    expect(instant.getMilliseconds()).toBe(999);
  });

  it.each([
    ["startOfDayIso", startOfDayIso],
    ["endOfDayIso", endOfDayIso],
  ])("%s never returns a naive instant", (_name, build) => {
    // A range end without a timezone is a 422 from the domain, so the `Z` is a
    // requirement and not a formatting detail.
    expect(build("2026-08-05")).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/,
    );
  });

  it("spans a single day, end after start", () => {
    const start = new Date(startOfDayIso("2026-08-05")!).getTime();
    const end = new Date(endOfDayIso("2026-08-05")!).getTime();

    expect(end).toBeGreaterThan(start);
    expect(end - start).toBe(24 * 60 * 60 * 1000 - 1);
  });

  it("handles a month and a year boundary", () => {
    expect(new Date(endOfDayIso("2026-01-31")!).getMonth()).toBe(0);
    expect(new Date(startOfDayIso("2027-01-01")!).getFullYear()).toBe(2027);
    // 2028 is a leap year: the 29th exists and stays the 29th.
    expect(new Date(startOfDayIso("2028-02-29")!).getDate()).toBe(29);
  });

  it("isInverseRange is true only when `to` precedes `from`", () => {
    expect(isInverseRange("2026-08-31", "2026-08-01")).toBe(true);
    expect(isInverseRange("2026-08-01", "2026-08-31")).toBe(false);
    // Equal ends are a valid one-day range, not an inverse one.
    expect(isInverseRange("2026-08-05", "2026-08-05")).toBe(false);
  });

  it("isInverseRange is false when either end is absent — the ends are independent", () => {
    expect(isInverseRange(undefined, "2026-08-01")).toBe(false);
    expect(isInverseRange("2026-08-31", undefined)).toBe(false);
    expect(isInverseRange(undefined, undefined)).toBe(false);
  });

  /*
    A cleared `<input type="date">` emits `''`, and these two behaviours are what
    make that safe: the builders return nothing instead of throwing `RangeError`
    from `toISOString()`, and `isInverseRange` does not read `'' < '2026-08-01'`
    as an inverted range. Both were raised by the security panel on sections 3-4.
  */
  it.each([
    ["an empty string", ""],
    ["a non-date", "abc"],
    ["a partial day", "2026-08"],
    ["an impossible month", "2026-13-05"],
    ["a day that month does not have", "2026-02-30"],
    ["a non-leap 29 February", "2027-02-29"],
    ["a year the Date constructor would remap", "0026-08-05"],
    ["a day with trailing content", "2026-08-05T00:00"],
  ])("returns nothing for %s rather than throwing", (_name, value) => {
    expect(startOfDayIso(value)).toBeUndefined();
    expect(endOfDayIso(value)).toBeUndefined();
  });

  it("treats a cleared end as no end, not as an inverse range", () => {
    expect(isInverseRange("2026-08-01", "")).toBe(false);
    expect(isInverseRange("", "2026-08-01")).toBe(false);
    expect(isInverseRange("2026-08-01", "nonsense")).toBe(false);
  });
});
