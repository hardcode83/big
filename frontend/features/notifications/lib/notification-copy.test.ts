import { describe, expect, it } from "vitest";

import esCatalogue from "@/locales/es/notifications.json";
import enCatalogue from "@/locales/en/notifications.json";

import {
  NOTIFICATION_COPY_KEYS,
  UNKNOWN_NOTIFICATION_COPY_KEY,
  notificationCopyKey,
} from "./notification-copy";

describe("notificationCopyKey (R4.1, R4.3, design D7/D14)", () => {
  it("covers the seventeen types with a key each, none of them the generic", () => {
    const entries = Object.entries(NOTIFICATION_COPY_KEYS);

    expect(entries).toHaveLength(17);
    for (const [type, key] of entries) {
      expect(key).toBe(`notifications:types.${type}`);
      expect(key).not.toBe(UNKNOWN_NOTIFICATION_COPY_KEY);
    }
    expect(new Set(entries.map(([, key]) => key)).size).toBe(17);
  });

  it("resolves every declared key against both catalogues, so no type paints as its id", () => {
    // The `Record` makes a MISSING type a typecheck failure; this is the other half — a type
    // that is in the map but not in the catalogue would render as the raw key string.
    for (const type of Object.keys(NOTIFICATION_COPY_KEYS)) {
      expect(esCatalogue.types).toHaveProperty(type);
      expect(enCatalogue.types).toHaveProperty(type);
      expect(
        (esCatalogue.types as Record<string, string>)[type].length,
      ).toBeGreaterThan(0);
      expect(
        (enCatalogue.types as Record<string, string>)[type].length,
      ).toBeGreaterThan(0);
    }
  });

  it("falls back to the translated generic for a value the interface does not know (R4.3)", () => {
    expect(notificationCopyKey("SOMETHING_FROM_BEFORE_THE_ENUM")).toBe(
      UNKNOWN_NOTIFICATION_COPY_KEY,
    );
    expect(notificationCopyKey("")).toBe(UNKNOWN_NOTIFICATION_COPY_KEY);
    expect(esCatalogue.types.unknown.length).toBeGreaterThan(0);
    expect(enCatalogue.types.unknown.length).toBeGreaterThan(0);
  });

  it("resolves a known type to its own key, not the generic", () => {
    expect(notificationCopyKey("CLEANING_TASK_ASSIGNED")).toBe(
      "notifications:types.CLEANING_TASK_ASSIGNED",
    );
  });

  it("never returns a key outside the notifications namespace", () => {
    const all = [...Object.values(NOTIFICATION_COPY_KEYS), UNKNOWN_NOTIFICATION_COPY_KEY];
    for (const key of all) {
      expect(key.startsWith("notifications:types.")).toBe(true);
    }
  });

  it("returns the generic for an inherited key, not an inherited function", () => {
    // A bare `KEYS[type] ?? GENERIC` hands back `Object.prototype.toString` here — a
    // function, which `??` does not catch, and `t()` would then echo
    // `function Object() { [native code] }` onto a cleaner's screen. `notification_type`
    // comes straight off the wire as free text with no runtime validation. Same shape as
    // `features/pricing/lib/decision-moves.test.ts`.
    for (const key of ["toString", "constructor", "valueOf", "hasOwnProperty", "__proto__"]) {
      const resolved = notificationCopyKey(key);
      expect(typeof resolved).toBe("string");
      expect(resolved).toBe(UNKNOWN_NOTIFICATION_COPY_KEY);
    }
  });
});
