import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatAge, formatConfidence, formatDateTime } from "./format";

const NOW = new Date("2026-08-19T12:00:00Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

function relative(value: number, unit: Intl.RelativeTimeFormatUnit, locale = "es") {
  return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(
    value,
    unit,
  );
}

describe("formatAge picks the coarsest unit that applies (task 2.4, D9, R1.2)", () => {
  it.each([
    ["2026-08-19T11:59:30Z", -30, "second"],
    ["2026-08-19T11:55:00Z", -5, "minute"],
    ["2026-08-19T09:00:00Z", -3, "hour"],
    ["2026-08-16T12:00:00Z", -3, "day"],
    ["2026-08-05T12:00:00Z", -2, "week"],
    ["2026-05-19T12:00:00Z", -3, "month"],
    ["2024-08-19T12:00:00Z", -2, "year"],
  ] as const)("renders %s as %i %s", (iso, value, unit) => {
    expect(formatAge(iso, "es")).toBe(relative(value, unit));
  });

  it("localizes with the active locale", () => {
    expect(formatAge("2026-08-19T09:00:00Z", "en")).toBe(
      relative(-3, "hour", "en"),
    );
    expect(formatAge("2026-08-19T09:00:00Z", "en")).not.toBe(
      formatAge("2026-08-19T09:00:00Z", "es"),
    );
  });

  it("returns null for a null timestamp instead of inventing a date (R1.3)", () => {
    expect(formatAge(null, "es")).toBeNull();
  });

  it("returns null for an unusable timestamp instead of throwing", () => {
    for (const iso of ["not-a-date", "", "2026-13-45T99:00:00Z"]) {
      expect(() => formatAge(iso, "es")).not.toThrow();
      expect(formatAge(iso, "es")).toBeNull();
    }
  });
});

describe("formatDateTime (task 2.4, D9)", () => {
  it("formats the absolute instant in the active locale", () => {
    expect(formatDateTime("2026-08-19T09:00:00Z", "es")).toBe(
      new Intl.DateTimeFormat("es", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date("2026-08-19T09:00:00Z")),
    );
  });

  it("returns null for a null timestamp, never an empty string (R1.3)", () => {
    expect(formatDateTime(null, "es")).toBeNull();
  });

  it("returns null for an unusable timestamp, never «Invalid Date»", () => {
    for (const iso of ["not-a-date", "", "2026-13-45T99:00:00Z"]) {
      expect(formatDateTime(iso, "es")).toBeNull();
    }
  });
});

describe("formatConfidence (task 2.4, D8, R3.4)", () => {
  it("formats the decimal string as a whole percentage", () => {
    expect(formatConfidence("0.8750", "es")).toBe(
      new Intl.NumberFormat("es", {
        style: "percent",
        maximumFractionDigits: 0,
      }).format(0.875),
    );
  });

  it("rounds only at render time, so a value the DTO kept unrounded still reads right", () => {
    expect(formatConfidence("0.874", "en")).toBe("87%");
    expect(formatConfidence("0.876", "en")).toBe("88%");
    expect(formatConfidence("1.0000", "en")).toBe("100%");
    expect(formatConfidence("0.0", "en")).toBe("0%");
  });

  it("renders no figure for a null score, and never null or NaN", () => {
    expect(formatConfidence(null, "es")).toBeNull();
    expect(formatConfidence("not-a-number", "es")).toBeNull();
    for (const value of [null, "not-a-number", ""]) {
      expect(String(formatConfidence(value, "es"))).not.toContain("NaN");
    }
  });
});
