import { describe, expect, it, vi } from "vitest";

import { fmtDay, fmtDecimal } from "./format";

describe("fmtDecimal (R6.1, R6.2)", () => {
  it("uses the decimal separator of the active locale", () => {
    // The reason `locale` is a parameter: with `toLocaleString(undefined, …)`
    // there is one separator per process and this assertion cannot exist.
    expect(fmtDecimal("1234.5", "es")).toBe("1234,50");
    expect(fmtDecimal("1234.5", "en")).toBe("1,234.50");
  });

  it("always shows exactly two decimals", () => {
    expect(fmtDecimal("120", "en")).toBe("120.00");
    expect(fmtDecimal("120.456", "en")).toBe("120.46");
    expect(fmtDecimal("0", "en")).toBe("0.00");
  });

  it("carries no currency symbol and no currency code", () => {
    // No pricing response has a `currency` field, so any symbol would be invented.
    const formatted = fmtDecimal("142.50", "es");
    expect(formatted).toBe("142,50");
    for (const token of ["€", "$", "EUR", "USD"]) {
      expect(formatted).not.toContain(token);
    }
  });

  it("returns the original string when the value is not a finite number", () => {
    // Better a truthful odd string than `NaN` where an amount should be.
    for (const value of ["n/a", "1.2.3", "Infinity", "NaN"]) {
      expect(fmtDecimal(value, "es")).toBe(value);
    }
  });

  it("treats the empty string as the finite zero it parses to, not as unparseable", () => {
    // `Number("") === 0`, and R6.1 only returns the original string when the
    // number is NOT finite — so this renders `0,00`. Pinned rather than left
    // implicit because it reads like a bug: it is the specified behaviour, and
    // the contract makes it unreachable (`recommended_price` and the four rule
    // amounts are non-nullable Decimal strings). If a requirement ever wants
    // "no amount" shown as such, it needs its own branch, not a change here.
    expect(fmtDecimal("", "es")).toBe("0,00");
  });
});

describe("fmtDay (R6.3)", () => {
  it("formats the ISO day in the active locale, without a time", () => {
    expect(fmtDay("2026-09-01", "en")).toBe("Sep 1, 2026");
    expect(fmtDay("2026-09-01", "es")).toBe("1 sept 2026");
  });

  it("never shifts the day when the machine's own timezone is west of UTC", () => {
    // `new Date("2026-01-01")` is midnight UTC, so formatting it in the reader's
    // zone prints 31 December anywhere west of UTC — the bug `timeZone: "UTC"`
    // exists to stop, and one that is invisible from Madrid.
    //
    // Simulating that machine is the whole difficulty. The test container runs
    // in UTC and `Intl` fixes its default zone at process start, so setting `TZ`
    // here changes nothing and an assertion on `fmtDay`'s output alone passes
    // just as happily with the guard deleted — it did, when checked. So the
    // simulation is done where it actually bites: any formatter built WITHOUT an
    // explicit `timeZone` gets a western one, exactly as a western browser would
    // supply. A `fmtDay` that names UTC is unaffected; a `fmtDay` that omits it
    // is caught.
    const Real = Intl.DateTimeFormat;
    // A `function`, not an arrow: it is invoked with `new`, and vitest says so.
    function WesternDateTimeFormat(
      locale?: string,
      options?: Intl.DateTimeFormatOptions,
    ) {
      return new Real(locale, {
        ...options,
        timeZone: options?.timeZone ?? "America/Los_Angeles",
      });
    }
    const spy = vi
      .spyOn(Intl, "DateTimeFormat")
      .mockImplementation(
        WesternDateTimeFormat as unknown as typeof Intl.DateTimeFormat,
      );

    try {
      // Guard on the guard: with no explicit zone the simulated machine really
      // does print the previous day, so the assertions below are not vacuous.
      expect(
        new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(
          new Date("2026-01-01"),
        ),
      ).toBe("Dec 31, 2025");

      expect(fmtDay("2026-01-01", "en")).toBe("Jan 1, 2026");
      expect(fmtDay("2026-01-01", "es")).toBe("1 ene 2026");
    } finally {
      spy.mockRestore();
    }
  });

  it("returns the original string for a day it cannot parse, instead of throwing", () => {
    // `Intl.format` raises `RangeError: Invalid time value` on an invalid date,
    // and `date` arrives straight off the wire. Degrading the way `fmtDecimal`
    // does keeps one malformed row from taking down the page.
    for (const value of ["", "nonsense", "2026-13-45"]) {
      expect(() => fmtDay(value, "es")).not.toThrow();
      expect(fmtDay(value, "es")).toBe(value);
    }
  });
});
