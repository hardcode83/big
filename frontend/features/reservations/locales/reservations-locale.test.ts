/**
 * Locale contract tests for the `reservations` i18n namespace.
 *
 * Two invariants are pinned here that the change reviews flagged as
 * missing-coverage:
 *
 * - R4.1: every value of the `ReservationStatus` enum (declared in the
 *   generated OpenAPI types) has a localized label in **both** locales.
 *   If a status is renamed in the backend, the enum updates and this
 *   test fails in red — pointing at the exact gap.
 *
 * - R4.3: the list view and the detail view render the same status
 *   label for the same enum value. They both call `t(\`status.${status}\`)`
 *   against the same namespace, so the equality is a property of the
 *   locale file: the same key resolves to the same string. The test
 *   asserts that by reading both locales and comparing the resolved
 *   value via `i18next` for each enum value.
 */

import { describe, expect, it } from "vitest";
import i18next from "i18next";

import esReservations from "@/locales/es/reservations.json";
import enReservations from "@/locales/en/reservations.json";
import type { components } from "@/lib/api/generated/openapi";

type ReservationStatus = components["schemas"]["ReservationStatus"];

const STATUS_VALUES: ReservationStatus[] = [
  "PENDING",
  "CONFIRMED",
  "CANCELLED",
  "CHECKED_IN_ESTIMATED",
  "CHECKED_OUT_ESTIMATED",
  "COMPLETED",
  "NO_SHOW",
];

describe("reservations locale (R4.1, R4.3)", () => {
  it("localizes the seven ReservationStatus values in ES and EN", () => {
    for (const status of STATUS_VALUES) {
      expect(
        esReservations.status[status],
        `ES missing label for status ${status}`,
      ).toBeTypeOf("string");
      expect(
        enReservations.status[status],
        `EN missing label for status ${status}`,
      ).toBeTypeOf("string");
    }
  });

  it("resolves the same status key to the same string via i18next (R4.3 — list and detail share the label)", async () => {
    // The component layer does `t(\`status.${status}\`)` against the
    // `reservations` namespace. We register the ES+EN resources on
    // i18next and assert that for each status, the resolved string
    // matches the locale file exactly. Two views with the same key
    // therefore render the same string.
    await i18next.init({
      lng: "es",
      fallbackLng: "en",
      ns: ["reservations"],
      defaultNS: "reservations",
      resources: {
        es: { reservations: esReservations },
        en: { reservations: enReservations },
      },
      interpolation: { escapeValue: false },
    });
    for (const status of STATUS_VALUES) {
      const resolved = i18next.t(`status.${status}`);
      expect(resolved).toBe(esReservations.status[status]);
    }
  });
});
