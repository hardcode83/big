/**
 * Locale contract tests for the `properties` i18n namespace (proposal R6).
 *
 * Why this file exists, and why it is not redundant with
 * `lib/i18n/catalog-parity.test.ts`: that test compares the *key sets* of the
 * ES and EN catalogs for every registered namespace, so it catches a key
 * present in one language and missing in the other. It does **not** check that
 * there is a key per enum value — an enum with twelve values and eleven labels
 * passes it, in both languages at once. Design D12 added this file for exactly
 * that gap, following the precedent of
 * `features/reservations/locales/reservations-locale.test.ts`, which exists
 * because a previous change review flagged the same hole as a real defect.
 *
 * It matters more here than in reservations for a reason specific to this
 * feature: design D10 has the screen read the ELEVEN operational-state labels
 * from the **`dashboard`** namespace rather than duplicating them. That is a
 * cross-namespace dependency — a change to `dashboard.json` can break this
 * screen — and nothing else in the tree would notice.
 */

import { describe, expect, it } from "vitest";
import i18next from "i18next";

import type { components } from "@/lib/api/generated/openapi";
import enDashboard from "@/locales/en/dashboard.json";
import esDashboard from "@/locales/es/dashboard.json";
import enProperties from "@/locales/en/properties.json";
import esProperties from "@/locales/es/properties.json";

type PropertyStatus = components["schemas"]["PropertyStatus"];
type PropertyOperationalState =
  components["schemas"]["PropertyOperationalState"];

/** The two `PropertyStatus` values, verified against the generated contract. */
const STATUS_VALUES: PropertyStatus[] = ["ACTIVE", "INACTIVE"];

/**
 * The eleven `PropertyOperationalState` values, verified against
 * `backend/app/properties/domain/enums.py`.
 */
const STATE_VALUES: PropertyOperationalState[] = [
  "VACANT_READY",
  "READY_FOR_NEXT_GUEST",
  "AWAITING_CHECKIN",
  "OCCUPIED_ESTIMATED",
  "CLEANING_IN_PROGRESS",
  "AWAITING_CLEANING",
  "CLEANING_SCHEDULED",
  "MAINTENANCE_REQUIRED",
  "CRITICAL_INCIDENT",
  "BLOCKED_BY_OWNER",
  "OUT_OF_SERVICE",
];

describe("properties locale — PropertyStatus (R6.1)", () => {
  it("localizes both status values in ES and EN", () => {
    for (const status of STATUS_VALUES) {
      expect(
        esProperties.status[status],
        `ES missing label for status ${status}`,
      ).toBeTypeOf("string");
      expect(
        enProperties.status[status],
        `EN missing label for status ${status}`,
      ).toBeTypeOf("string");
    }
  });

  it("has no label for a status the contract does not declare", () => {
    // Guards the other direction: a leftover label for a removed enum value is
    // dead copy that suggests a state the product no longer has.
    expect(Object.keys(esProperties.status).sort()).toEqual(
      [...STATUS_VALUES].sort(),
    );
    expect(Object.keys(enProperties.status).sort()).toEqual(
      [...STATUS_VALUES].sort(),
    );
  });
});

describe("properties locale — operational state read from `dashboard` (R6.3, design D10)", () => {
  it("localizes the eleven operational states in ES and EN", () => {
    // The screen reads these with `useTranslation("dashboard")` instead of
    // duplicating them, so this is where that cross-namespace decision is held
    // to account.
    for (const state of STATE_VALUES) {
      expect(
        (esDashboard.state as Record<string, string>)[state],
        `ES missing dashboard label for state ${state}`,
      ).toBeTypeOf("string");
      expect(
        (enDashboard.state as Record<string, string>)[state],
        `EN missing dashboard label for state ${state}`,
      ).toBeTypeOf("string");
    }
  });

  it("does not duplicate the state catalog inside the properties namespace", () => {
    // D10: "Dos catálogos del mismo enum es como divergen." If someone adds a
    // `state` block here, this fails and points at the decision.
    expect(esProperties).not.toHaveProperty("state");
    expect(enProperties).not.toHaveProperty("state");
  });
});

describe("properties locale — resolution through i18next", () => {
  it("resolves the keys the screen actually asks for, across both namespaces", async () => {
    await i18next.init({
      lng: "es",
      fallbackLng: "en",
      ns: ["properties", "dashboard"],
      defaultNS: "properties",
      resources: {
        es: { properties: esProperties, dashboard: esDashboard },
        en: { properties: enProperties, dashboard: enDashboard },
      },
      interpolation: { escapeValue: false },
    });

    for (const status of STATUS_VALUES) {
      expect(i18next.t(`status.${status}`)).toBe(esProperties.status[status]);
    }
    for (const state of STATE_VALUES) {
      expect(i18next.t(`dashboard:state.${state}`)).toBe(
        (esDashboard.state as Record<string, string>)[state],
      );
    }
    // The six column headers the table renders (R1.2).
    for (const column of [
      "name",
      "internalCode",
      "city",
      "capacity",
      "operationalState",
      "status",
    ] as const) {
      expect(i18next.t(`columns.${column}`)).toBe(
        esProperties.columns[column],
      );
    }
  });
});
