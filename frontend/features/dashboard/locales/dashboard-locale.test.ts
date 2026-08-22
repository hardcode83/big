import { describe, expect, it } from "vitest";

import esDashboard from "@/locales/es/dashboard.json";
import enDashboard from "@/locales/en/dashboard.json";

import { TIMELINE_EVENT_TYPES } from "../lib/timeline-event-types";

/**
 * Locale contract for the `dashboard` namespace, in the shape of
 * `features/reservations/locales/reservations-locale.test.ts`.
 *
 * The type filter offers the closed enum, so a missing label is not a cosmetic
 * gap — the option would render blank (R2.5 removed the raw-enum fallback). 47
 * labels × 2 locales is mechanical work, so the gap is checked rather than
 * trusted. Symmetry between es and en is already enforced by
 * `lib/i18n/catalog-parity.test.ts`; `TIMELINE_EVENT_TYPES` is pinned to the
 * published enum by `lib/timeline-event-types.test.ts`.
 */
const LOCALES = {
  es: esDashboard.timeline.eventType as Record<string, string | undefined>,
  en: enDashboard.timeline.eventType as Record<string, string | undefined>,
};

describe("dashboard locale — timeline event types (R2.3, R2.4)", () => {
  it("labels every TimelineEventType in ES and EN", () => {
    for (const type of TIMELINE_EVENT_TYPES) {
      for (const [locale, labels] of Object.entries(LOCALES)) {
        expect(labels[type], `${locale} missing label for ${type}`).toBeTypeOf(
          "string",
        );
        expect(labels[type], `${locale} empty label for ${type}`).not.toBe("");
      }
    }
  });

  it("carries no interpolation marker copied from the server catalog", () => {
    // The server titles for RESERVATION_IMPORTED and PROPERTY_STATE_CHANGED
    // interpolate `{source}` / `{to_state}`; a filter label has no event to
    // substitute from, so R2.4 drops the marker and the preposition with it.
    for (const type of TIMELINE_EVENT_TYPES) {
      for (const [locale, labels] of Object.entries(LOCALES)) {
        expect(labels[type], `${locale} label for ${type}`).not.toContain("{");
      }
    }
  });
});
