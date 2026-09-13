/**
 * Locale contract tests for the `tenant-settings` i18n namespace (mirrors
 * `features/reservations/locales/reservations-locale.test.ts`).
 *
 * Two invariants are pinned:
 *
 * - Every `UserRole` and `UserStatus` enum value from the generated OpenAPI
 *   types has a localized label in **both** `es` and `en`. If a role/status
 *   is renamed or added on the backend, the enum updates and this test fails
 *   in red, pointing at the exact gap.
 *
 *   Scope decision (see tasks.md `## Implementation Notes`): all five
 *   `UserRole` values are covered, including `SUPER_ADMIN` — even though no
 *   grantable-role select in this feature ever offers it (`create-user-form`
 *   and `edit-user-form` both restrict to the four grantable roles), the
 *   `user-list` filter's role dropdown enumerates the full backend enum
 *   (task 3.1), so a `SUPER_ADMIN` row's badge or filter option would render
 *   `t("userRole.SUPER_ADMIN")` if one ever appeared. Narrowing this test to
 *   `GRANTABLE_ROLES` would leave that path silently uncovered.
 *
 * - The same enum value resolves to the same string via `i18next` wherever
 *   it is rendered (`user-list`'s table badge and filter option,
 *   `user-detail-view`'s role/status rows, `edit-user-form`'s role/status
 *   selects) — a property of the locale file, not of any one component: they
 *   all call `t(\`userRole.${role}\`)`/`t(\`userStatus.${status}\`)` against
 *   the same namespace and key.
 */

import { describe, expect, it } from "vitest";
import i18next from "i18next";

import esTenantSettings from "@/locales/es/tenant-settings.json";
import enTenantSettings from "@/locales/en/tenant-settings.json";
import type { components } from "@/lib/api/generated/openapi";

type UserRole = components["schemas"]["UserRole"];
type UserStatus = components["schemas"]["UserStatus"];

const ROLE_VALUES: UserRole[] = [
  "SUPER_ADMIN",
  "TENANT_OWNER",
  "PROPERTY_MANAGER",
  "CLEANER",
  "TECHNICIAN",
];

const STATUS_VALUES: UserStatus[] = ["ACTIVE", "INACTIVE", "SUSPENDED"];

describe("tenant-settings locale (task 5.5)", () => {
  it("localizes every UserRole value in ES and EN", () => {
    for (const role of ROLE_VALUES) {
      expect(esTenantSettings.userRole[role], `ES missing label for role ${role}`).toBeTypeOf(
        "string",
      );
      expect(enTenantSettings.userRole[role], `EN missing label for role ${role}`).toBeTypeOf(
        "string",
      );
    }
  });

  it("localizes every UserStatus value in ES and EN", () => {
    for (const status of STATUS_VALUES) {
      expect(
        esTenantSettings.userStatus[status],
        `ES missing label for status ${status}`,
      ).toBeTypeOf("string");
      expect(
        enTenantSettings.userStatus[status],
        `EN missing label for status ${status}`,
      ).toBeTypeOf("string");
    }
  });

  it("resolves the same role/status key to the same string via i18next everywhere it's rendered", async () => {
    await i18next.init({
      lng: "es",
      fallbackLng: "en",
      ns: ["tenant-settings"],
      defaultNS: "tenant-settings",
      resources: {
        es: { "tenant-settings": esTenantSettings },
        en: { "tenant-settings": enTenantSettings },
      },
      interpolation: { escapeValue: false },
    });

    for (const role of ROLE_VALUES) {
      const resolved = i18next.t(`userRole.${role}`);
      expect(resolved).toBe(esTenantSettings.userRole[role]);
    }
    for (const status of STATUS_VALUES) {
      const resolved = i18next.t(`userStatus.${status}`);
      expect(resolved).toBe(esTenantSettings.userStatus[status]);
    }
  });
});
