import { describe, expect, it } from "vitest";

import { waitingSince } from "./waiting-since";

const NOW = new Date("2026-09-05T12:00:00.000Z");

describe("waitingSince (R2.1)", () => {
  it("returns null for a missing/blank timestamp", () => {
    expect(waitingSince("", NOW)).toBeNull();
    expect(waitingSince("   ", NOW)).toBeNull();
  });

  it("returns null for an unparseable timestamp", () => {
    expect(waitingSince("not-a-date", NOW)).toBeNull();
  });

  it("floors to at least 1 minute for a just-created row", () => {
    const requestedAt = new Date(NOW.getTime() - 5 * 1000).toISOString(); // 5s ago
    expect(waitingSince(requestedAt, NOW)).toEqual({ unit: "minutes", count: 1 });
  });

  it("reports whole minutes under the one-hour boundary", () => {
    const requestedAt = new Date(NOW.getTime() - 45 * 60 * 1000).toISOString(); // 45m ago
    expect(waitingSince(requestedAt, NOW)).toEqual({ unit: "minutes", count: 45 });
  });

  it("switches to hours exactly at the one-hour boundary", () => {
    const requestedAt = new Date(NOW.getTime() - 60 * 60 * 1000).toISOString(); // exactly 1h
    expect(waitingSince(requestedAt, NOW)).toEqual({ unit: "hours", count: 1 });
  });

  it("reports whole hours under the one-day boundary", () => {
    const requestedAt = new Date(NOW.getTime() - 3 * 60 * 60 * 1000).toISOString(); // 3h ago
    expect(waitingSince(requestedAt, NOW)).toEqual({ unit: "hours", count: 3 });
  });

  it("switches to days exactly at the one-day boundary", () => {
    const requestedAt = new Date(
      NOW.getTime() - 24 * 60 * 60 * 1000,
    ).toISOString(); // exactly 1 day
    expect(waitingSince(requestedAt, NOW)).toEqual({ unit: "days", count: 1 });
  });

  it("reports whole days for a long-pending approval", () => {
    const requestedAt = new Date(
      NOW.getTime() - 9 * 24 * 60 * 60 * 1000,
    ).toISOString(); // 9 days ago
    expect(waitingSince(requestedAt, NOW)).toEqual({ unit: "days", count: 9 });
  });

  it("never goes negative for a clock-skewed future timestamp", () => {
    const requestedAt = new Date(NOW.getTime() + 60 * 1000).toISOString(); // 1m in the future
    expect(waitingSince(requestedAt, NOW)).toEqual({ unit: "minutes", count: 1 });
  });
});
