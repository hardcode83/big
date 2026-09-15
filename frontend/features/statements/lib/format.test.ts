import { describe, expect, it, vi } from "vitest";

import { absentAmount, fmtAmount, fmtCurrency, fmtDay } from "./format";

describe("fmtDay (R5.4 — UTC-anchored, locale-aware, no throw)", () => {
  it("formats an ISO day in the active locale, without a time", () => {
    expect(fmtDay("2026-09-01", "en")).toBe("Sep 1, 2026");
    expect(fmtDay("2026-09-01", "es")).toBe("1 sept 2026");
  });

  it("never shifts the day when the machine's timezone is west of UTC", () => {
    // Same simulation trick as `features/pricing/lib/format.test.ts`:
    // replacing `Intl.DateTimeFormat` with a western-zone one makes the
    // guard on `timeZone: "UTC"` actually meaningful — without it the test
    // passes just as happily with the guard deleted (it did, when checked).
    const Real = Intl.DateTimeFormat;
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
      // Guard on the guard: with no explicit zone the simulated machine
      // really does print the previous day, so the assertion below is not
      // vacuous.
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

  it("returns the original string for an unparseable day, instead of throwing", () => {
    for (const value of ["", "nonsense", "2026-13-45"]) {
      expect(() => fmtDay(value, "es")).not.toThrow();
      expect(fmtDay(value, "es")).toBe(value);
    }
  });
});

describe("fmtAmount (R3.6 — locale decimals, no currency symbol/code)", () => {
  it("uses the decimal separator of the active locale", () => {
    expect(fmtAmount("1234.5", "es")).toBe("1234,50");
    expect(fmtAmount("1234.5", "en")).toBe("1,234.50");
  });

  it("always shows exactly two decimals", () => {
    expect(fmtAmount("120", "en")).toBe("120.00");
    expect(fmtAmount("120.456", "en")).toBe("120.46");
    expect(fmtAmount("0", "en")).toBe("0.00");
  });

  it("carries no currency symbol and no currency code", () => {
    // The summary has no `currency` field — adding a symbol here would
    // invent a global currency the backend never published.
    const formatted = fmtAmount("142.50", "es");
    expect(formatted).toBe("142,50");
    for (const token of ["€", "$", "EUR", "USD"]) {
      expect(formatted).not.toContain(token);
    }
  });

  it("returns the original string when the value is not a finite number", () => {
    // Better a truthful odd string than `NaN` where an amount should be.
    for (const value of ["n/a", "1.2.3", "Infinity", "NaN"]) {
      expect(fmtAmount(value, "es")).toBe(value);
    }
  });

  it("treats the empty string as the finite zero it parses to, not as unparseable", () => {
    // `Number("") === 0`, and `fmtAmount` only falls back when the number is
    // NOT finite — so this renders `0,00`. The contract makes it unreachable
    // (the eleven summary amounts are non-nullable Decimal strings), so this
    // pins behaviour rather than chasing a phantom edge case.
    expect(fmtAmount("", "es")).toBe("0,00");
  });
});

describe("fmtCurrency (R3.6 — per-row currency, graceful fallback for unknown codes)", () => {
  it("paints the locale's symbol for EUR in es and en", () => {
    const esValue = fmtCurrency("1234.5", "EUR", "es");
    const enValue = fmtCurrency("1234.5", "EUR", "en");
    // ES uses the suffix `€` (e.g. `1234,50 €`); EN uses the prefix
    // `€1,234.50`. We assert the locale's decimal pattern and the presence
    // of the symbol rather than the exact glyph sequence — that pins the
    // contract without binding the test to a specific ICU build (which is
    // exactly the unknown-currency-code concern this formatter exists to
    // handle).
    expect(esValue).toContain("1234,50");
    expect(esValue).toMatch(/€/);
    expect(enValue).toContain("1,234.50");
    expect(enValue).toMatch(/€/);
  });

  it("uses a USD-specific symbol and respects locale-specific formatting for USD", () => {
    const usd = fmtCurrency("1234.5", "USD", "en");
    expect(usd).toContain("1,234.50");
    expect(usd).toMatch(/\$/);
  });

  it("falls back to '<decimal> <code>' instead of throwing on an unknown currency code", () => {
    // `Intl.NumberFormat` raises `RangeError: Invalid currency code : XYZ`
    // for codes it does not know; the contract never sends those, but the
    // server-side codes are open and we do not validate them client-side.
    // The fallback keeps one pathological row from taking down the page.
    const spy = vi.spyOn(Intl, "NumberFormat");
    try {
      spy.mockImplementationOnce(() => {
        throw new RangeError("Invalid currency code : XYZ");
      });
      expect(fmtCurrency("99.50", "XYZ", "es")).toBe("99,50 XYZ");
      expect(fmtCurrency("99.50", "XYZ", "en")).toBe("99.50 XYZ");
    } finally {
      spy.mockRestore();
    }
  });

  it("returns the original string when the value is not a finite number", () => {
    // Same shape as `fmtAmount`: a non-finite value degrades to the raw
    // input rather than throwing or showing `NaN`.
    expect(fmtCurrency("n/a", "EUR", "es")).toBe("n/a");
  });

  it("never converts between currencies or aggregates across rows", () => {
    // The two calls below are independent — neither one mutates the other's
    // output, no global symbol leaks across them. The formatter has no
    // state.
    const eur = fmtCurrency("100.00", "EUR", "es");
    const usd = fmtCurrency("100.00", "USD", "es");
    expect(eur).toMatch(/€/);
    expect(usd).toMatch(/\$/);
    expect(eur).not.toBe(usd);
  });
});

describe("absentAmount (R3.5 — i18n'd '—' marker, never 0, never a substitute)", () => {
  it("returns the localized absent marker for ES and EN", () => {
    // The marker resolves through the active i18next catalog — the parity
    // test in `lib/i18n/catalog-parity.test.ts` keeps ES and EN identical,
    // so reading the catalog directly here is equivalent to going through
    // i18next.
    expect(absentAmount("es")).toBe("—");
    expect(absentAmount("en")).toBe("—");
  });

  it("is never a numeric substitution", () => {
    const marker = absentAmount("es");
    expect(marker).not.toBe("0");
    expect(marker).not.toBe("0,00");
    expect(marker).not.toBe("0.00");
    // And not a `Number`-coerced zero either.
    expect(Number.isNaN(Number(marker))).toBe(true);
  });
});
