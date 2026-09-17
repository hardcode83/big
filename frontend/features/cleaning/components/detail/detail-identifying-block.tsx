"use client";

import { useTranslation } from "react-i18next";

import type { CleaningTask, PropertySummary } from "../../data";
import { resolveIdentity, type Directory, type Identity } from "../../lib/directory";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-label-caps uppercase text-muted-foreground">
        {label}
      </span>
      <span className="min-w-0 break-words text-body-medium text-foreground">
        {children}
      </span>
    </div>
  );
}

/**
 * The identifying block of `/cleaning/[id]` (proposal R3.1/R3.2/R3.4,
 * design D6/D8).
 *
 * Three pieces of data:
 *
 * - `internalCode · name` of the property, resolved against the directory
 *   the caller already loaded (D6: `usePropertyDirectory()`, never a new
 *   fetch per detail). The raw `property_id` is **never** rendered — the
 *   proposal R3.1 says so, and the listing's `cleaning-task-row.tsx:189-201`
 *   applies the same rule with `IdentityValue`.
 * - the reservation `id`, painted as the code (the backend publishes only
 *   the id; the codebase's `IncidentDetailView` does the same, the precedent
 *   the proposal points to). A `null` reservation id renders the
 *   "no reservation" indicator (R3.2).
 * - a degraded "no disponible" indicator when the property is not in the
 *   directory the caller handed us (R3.4 — same degradation the listing
 *   already declares for unresolvable identities).
 */
export interface DetailIdentifyingBlockProps {
  propertyId: CleaningTask["propertyId"];
  reservationId: CleaningTask["reservationId"];
  properties: Directory<PropertySummary>;
}

export function DetailIdentifyingBlock({
  propertyId,
  reservationId,
  properties,
}: DetailIdentifyingBlockProps) {
  const { t } = useTranslation("cleaning");
  const property: Identity<PropertySummary> = resolveIdentity(
    propertyId,
    properties,
  );
  return (
    <section className="border-b border-border py-4">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("detail.identifying.propertyCode")}>
          {property.kind === "resolved"
            ? property.value.internalCode
            : t("detail.identifying.propertyNotFound")}
        </Field>
        <Field label={t("detail.identifying.propertyName")}>
          {property.kind === "resolved"
            ? property.value.name
            : t("detail.identifying.propertyNotFound")}
        </Field>
        <Field label={t("detail.identifying.reservationCode")}>
          {reservationId !== null
            ? reservationId
            : t("detail.identifying.reservationNotFound")}
        </Field>
      </dl>
    </section>
  );
}