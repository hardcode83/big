"use client";

import { useTranslation } from "react-i18next";

import type { CleanerSummary, CleaningTask } from "../../data";
import { resolveIdentity, type Directory, type Identity } from "../../lib/directory";

/**
 * The assigned-cleaner block of `/cleaning/[id]` (proposal R3.3/R3.4,
 * design D8).
 *
 * Reuses `Identity<T>` from `lib/directory` — the same four-shape
 * (`unassigned` / `pending` / `unavailable` / `resolved`) the listing's
 * `cleaning-task-row.tsx:127-158` declares. The contract is identical:
 *
 * - `unassigned` → translated "unassigned" copy (R3.3, distinct from "not
 *   available" — `cleaning-manager-view` D5 makes the four shapes
 *   distinguishable, and section 4's view inherits that).
 * - `pending` → empty marker (catalog still in flight, R3.5).
 * - `unavailable` → italic translated "identity not available" (R3.4).
 * - `resolved` → the cleaner's name.
 *
 * The block is **not** gated on `MANAGE_CLEANING_TASKS`: a `TENANT_OWNER`
 * reading the detail has to see who is assigned too, the same way
 * `IncidentDetailView`'s technician block is unconditional for the same role
 * (`features/incidents/components/detail/incident-detail-view.tsx:37-39`,
 * R2.6 of the incidents proposal). Only the read contract applies.
 */
export interface DetailAssignedCleanerBlockProps {
  assignedCleanerId: CleaningTask["assignedCleanerId"];
  cleaners: Directory<CleanerSummary>;
}

export function DetailAssignedCleanerBlock({
  assignedCleanerId,
  cleaners,
}: DetailAssignedCleanerBlockProps) {
  const { t } = useTranslation("cleaning");
  const identity: Identity<CleanerSummary> = resolveIdentity(
    assignedCleanerId,
    cleaners,
  );
  let body: React.ReactNode;
  switch (identity.kind) {
    case "unassigned":
      body = t("detail.assigned.unassigned");
      break;
    case "pending":
      body = (
        <>
          <span aria-hidden="true">—</span>
          <span className="sr-only">{t("identity.loading")}</span>
        </>
      );
      break;
    case "unavailable":
      body = t("detail.assigned.notFound");
      break;
    case "resolved":
      body = identity.value.name;
      break;
  }
  return (
    <section className="border-b border-border py-4">
      <dl>
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-label-caps uppercase text-muted-foreground">
            {t("detail.assigned.label")}
          </span>
          <span className="min-w-0 break-words text-body-medium text-foreground">
            {body}
          </span>
        </div>
      </dl>
    </section>
  );
}