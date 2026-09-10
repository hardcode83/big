import { describe, expect, it } from "vitest";

import {
  NOTIFICATION_DESTINATIONS,
  NOTIFICATION_TYPE_DESTINATIONS,
  notificationHref,
} from "./notification-destinations";

// A neutral placeholder for `type` in tests that only exercise the `related_type` table — no
// row in `NOTIFICATION_TYPE_DESTINATIONS` carries this key, so it never short-circuits.
const NO_TYPE_OVERRIDE = "SOME_OTHER_NOTIFICATION_TYPE";

describe("notificationHref (R5.1, R5.2, R5.3, R5.4, R6.1, R6.2, R6.3, design D8, D15)", () => {
  it("links the three workspace related_types to the pages that exist", () => {
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", "incident", "i1")).toBe(
      "/incidents/i1",
    );
    expect(
      notificationHref(NO_TYPE_OVERRIDE, "workspace", "conversation", "c1"),
    ).toBe("/conversations/c1");
    expect(
      notificationHref(NO_TYPE_OVERRIDE, "workspace", "reservation", "r1"),
    ).toBe("/reservations/r1");
  });

  it("links nothing in the cleaner shell, whose detail pages are still placeholders (R6.2, R5.4)", () => {
    for (const type of ["incident", "conversation", "reservation", "cleaning_task"]) {
      expect(notificationHref(NO_TYPE_OVERRIDE, "cleaner", type, "x1")).toBeNull();
    }
  });

  it("never links a cleaning task, which has no manager detail page (R6.2)", () => {
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", "cleaning_task", "t1")).toBeNull();
    expect(NOTIFICATION_DESTINATIONS.workspace).not.toHaveProperty("cleaning_task");
  });

  it("returns null — never the id — when either half of the pair is missing (R6.3)", () => {
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", null, "i1")).toBeNull();
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", "incident", null)).toBeNull();
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", null, null)).toBeNull();
  });

  it("returns null for a related_type the table does not carry (R6.3)", () => {
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", "property", "p1")).toBeNull();
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", "", "p1")).toBeNull();
  });

  it("declares every shell profile, so a missing one is a typecheck failure and not a silent null", () => {
    // R6.4: the profile is a dimension of the table. Filling in `cleaner` the day
    // `cleaner-app` ships must be one cell, which requires the row to already be there.
    expect(Object.keys(NOTIFICATION_DESTINATIONS).sort()).toEqual([
      "authenticated",
      "cleaner",
      "guest",
      "platform",
      "public",
      "technician",
      "workspace",
    ]);
  });

  it("builds an href that carries the id and nothing else", () => {
    const href = notificationHref(NO_TYPE_OVERRIDE, "workspace", "incident", "abc-123");
    expect(href).toBe("/incidents/abc-123");
    expect(href).not.toContain("undefined");
  });

  it("returns no href for an inherited related_type key, in every profile (R6.3)", () => {
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
        expect(() =>
          notificationHref(NO_TYPE_OVERRIDE, profile, key, "leaked-uuid"),
        ).not.toThrow();
        expect(notificationHref(NO_TYPE_OVERRIDE, profile, key, "leaked-uuid")).toBeNull();
      }
    }
  });

  it("still resolves the real destinations after the guard", () => {
    expect(notificationHref(NO_TYPE_OVERRIDE, "workspace", "incident", "i1")).toBe(
      "/incidents/i1",
    );
  });

  describe("type-keyed destinations (R5.1, R5.3, R5.4, design D8)", () => {
    it("links OWNER_APPROVAL_REQUIRED in the workspace shell to /approvals", () => {
      expect(
        notificationHref("OWNER_APPROVAL_REQUIRED", "workspace", null, null),
      ).toBe("/approvals");
      expect(
        notificationHref("OWNER_APPROVAL_REQUIRED", "workspace", "anything", "x1"),
      ).toBe("/approvals");
    });

    it("does not link OWNER_APPROVAL_REQUIRED outside the workspace shell", () => {
      for (const profile of ["cleaner", "technician", "public", "guest", "authenticated", "platform"] as const) {
        expect(notificationHref("OWNER_APPROVAL_REQUIRED", profile, null, null)).toBeNull();
      }
    });

    it("falls through to the related_type table for a type with no override", () => {
      expect(
        notificationHref("INCIDENT_CREATED_HIGH", "workspace", "incident", "i1"),
      ).toBe("/incidents/i1");
    });

    it("resolves an incident in the technician shell to /tech/incidents/{id} (R5.2)", () => {
      expect(
        notificationHref("TECHNICIAN_ASSIGNED", "technician", "incident", "i1"),
      ).toBe("/tech/incidents/i1");
      expect(
        notificationHref("OWNER_APPROVAL_APPROVED", "technician", "incident", "i1"),
      ).toBe("/tech/incidents/i1");
      expect(
        notificationHref("OWNER_APPROVAL_REJECTED", "technician", "incident", "i1"),
      ).toBe("/tech/incidents/i1");
    });

    it("falls through with no type override, and returns null when either half of the related_type pair is missing (R5.3)", () => {
      expect(notificationHref(NO_TYPE_OVERRIDE, "technician", "incident", null)).toBeNull();
      expect(notificationHref(NO_TYPE_OVERRIDE, "technician", null, "i1")).toBeNull();
    });

    it("leaves cleaner empty in the type table too (R5.4)", () => {
      expect(NOTIFICATION_TYPE_DESTINATIONS.cleaner).toEqual({});
    });

    it("returns no href for an inherited key on the type table, in every profile", () => {
      for (const profile of [
        "workspace",
        "cleaner",
        "technician",
        "public",
        "guest",
        "authenticated",
        "platform",
      ] as const) {
        for (const key of ["toString", "constructor", "valueOf", "hasOwnProperty", "__proto__"]) {
          expect(() => notificationHref(key, profile, null, null)).not.toThrow();
          expect(notificationHref(key, profile, null, null)).toBeNull();
        }
      }
    });

    it("declares every shell profile in the type table too", () => {
      expect(Object.keys(NOTIFICATION_TYPE_DESTINATIONS).sort()).toEqual([
        "authenticated",
        "cleaner",
        "guest",
        "platform",
        "public",
        "technician",
        "workspace",
      ]);
    });
  });
});
