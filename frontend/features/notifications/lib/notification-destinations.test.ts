import { describe, expect, it } from "vitest";

import {
  NOTIFICATION_DESTINATIONS,
  notificationHref,
} from "./notification-destinations";

describe("notificationHref (R6.1, R6.2, R6.3, design D15)", () => {
  it("links the three workspace types to the pages that exist", () => {
    expect(notificationHref("workspace", "incident", "i1")).toBe("/incidents/i1");
    expect(notificationHref("workspace", "conversation", "c1")).toBe(
      "/conversations/c1",
    );
    expect(notificationHref("workspace", "reservation", "r1")).toBe(
      "/reservations/r1",
    );
  });

  it("links nothing in the field shells, whose detail pages are still placeholders (R6.2)", () => {
    for (const profile of ["cleaner", "technician"] as const) {
      for (const type of ["incident", "conversation", "reservation", "cleaning_task"]) {
        expect(notificationHref(profile, type, "x1")).toBeNull();
      }
    }
  });

  it("never links a cleaning task, which has no manager detail page (R6.2)", () => {
    expect(notificationHref("workspace", "cleaning_task", "t1")).toBeNull();
    expect(NOTIFICATION_DESTINATIONS.workspace).not.toHaveProperty("cleaning_task");
  });

  it("returns null — never the id — when either half of the pair is missing (R6.3)", () => {
    expect(notificationHref("workspace", null, "i1")).toBeNull();
    expect(notificationHref("workspace", "incident", null)).toBeNull();
    expect(notificationHref("workspace", null, null)).toBeNull();
  });

  it("returns null for a related_type the table does not carry (R6.3)", () => {
    expect(notificationHref("workspace", "property", "p1")).toBeNull();
    expect(notificationHref("workspace", "", "p1")).toBeNull();
  });

  it("declares every shell profile, so a missing one is a typecheck failure and not a silent null", () => {
    // R6.4: the profile is a dimension of the table. Filling in `cleaner` the day
    // `cleaner-app` ships must be one cell, which requires the row to already be there.
    expect(Object.keys(NOTIFICATION_DESTINATIONS).sort()).toEqual([
      "authenticated",
      "cleaner",
      "guest",
      "public",
      "technician",
      "workspace",
    ]);
  });

  it("builds an href that carries the id and nothing else", () => {
    const href = notificationHref("workspace", "incident", "abc-123");
    expect(href).toBe("/incidents/abc-123");
    expect(href).not.toContain("undefined");
  });

  it("returns no href for an inherited key, in every profile (R6.3)", () => {
    // Here the guard is load-bearing rather than defence in depth: a `typeof === "function"`
    // check alone would PASS for `Object.prototype.valueOf`, which is then called unbound and
    // throws `Cannot convert undefined or null to object` — inside a topbar the field shells
    // mount above their own AuthGuard, so it took down the whole chrome (D16).
    for (const profile of [
      "workspace",
      "cleaner",
      "technician",
      "public",
      "guest",
      "authenticated",
    ] as const) {
      for (const key of ["toString", "constructor", "valueOf", "hasOwnProperty", "__proto__"]) {
        expect(() => notificationHref(profile, key, "leaked-uuid")).not.toThrow();
        expect(notificationHref(profile, key, "leaked-uuid")).toBeNull();
      }
    }
  });

  it("still resolves the real destinations after the guard", () => {
    expect(notificationHref("workspace", "incident", "i1")).toBe("/incidents/i1");
  });
});
