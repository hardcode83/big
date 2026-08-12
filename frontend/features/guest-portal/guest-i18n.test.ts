import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/openapi";
import es from "@/locales/es/guest.json";
import en from "@/locales/en/guest.json";

/** Recursively collects the dotted key paths of a nested translation object. */
function keyPaths(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    keyPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

const DOCUMENT_TYPES: components["schemas"]["GuestDocumentType"][] = ["DNI", "NIE", "PASSPORT", "RESIDENCE_CARD", "OTHER"];
const DOCUMENT_STATUSES: components["schemas"]["GuestDocumentStatus"][] = ["NOT_PROVIDED", "PENDING", "PROVIDED", "VERIFIED", "REJECTED"];
const LEGAL_STATUSES: components["schemas"]["LegalRegistrationStatus"][] = ["NOT_REQUIRED", "PENDING_GUEST_DATA", "READY_TO_SUBMIT", "SUBMITTED", "FAILED", "MANUAL_REVIEW"];
const INCIDENT_STATUSES: components["schemas"]["IncidentStatus"][] = ["OPEN", "CLASSIFIED", "AWAITING_OWNER_APPROVAL", "ASSIGNED", "ACCEPTED", "IN_PROGRESS", "WAITING_EXTERNAL_PARTS", "RESOLVED", "CANCELLED"];

describe("guest i18n catalogs (R4.1)", () => {
  it("has identical key sets in es and en", () => {
    const esKeys = keyPaths(es).sort();
    const enKeys = keyPaths(en).sort();
    expect(esKeys).toEqual(enKeys);
  });

  it("covers every enum member the UI renders, in both locales", () => {
    for (const locale of [es, en] as const) {
      for (const value of DOCUMENT_TYPES) expect(locale.documentTypes).toHaveProperty(value);
      // document_status and legal_registration_status are both rendered via guest:status.*
      for (const value of [...DOCUMENT_STATUSES, ...LEGAL_STATUSES]) expect(locale.status).toHaveProperty(value);
      for (const value of INCIDENT_STATUSES) expect(locale.incident.status).toHaveProperty(value);
    }
  });

  it("provides the accessible state copy each journey needs, in both locales", () => {
    for (const locale of [es, en] as const) {
      for (const key of ["loading", "retry", "unavailable"] as const) expect(locale[key]).toBeTruthy();
      for (const key of ["title", "generic", "rateLimit", "tooLarge", "validation", "required", "invalidField"] as const)
        expect(locale.errors[key]).toBeTruthy();
      expect(locale.invalid.title).toBeTruthy();
      expect(locale.invalid.description).toBeTruthy();
    }
  });
});
