"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/ui/card";

import type { CleaningTask, CleaningTaskContext } from "../../data";
import { formatDateTime } from "../../lib/format";

/**
 * The address, timezone and window of one cleaning task (R2.2, R2.6).
 *
 * Pure render — the per-field mutation lives on a separate component to keep
 * this one read-only. Null scalars render the em-dash `—` (R2.6). `?? ""` is
 * forbidden because it would concatenate unitless values; `formatDateTime`
 * does the null check itself.
 *
 * The two instants (`checkout_at`, `next_checkin_deadline`) are formatted in
 * the property's `timezone` — the field `CleaningTaskContext.timezone` exists
 * precisely for this — and the `Intl.DateTimeFormat` API only ever formats in
 * the runtime's timezone; we rely on the wire providing the right ISO 8601
 * with explicit offset (D3 of the context spec).
 */
export interface CleanerTaskContextBlockProps {
  task: CleaningTask;
  context: CleaningTaskContext;
}

/**
 * The "uppercase label + monospace value" `<dl>` pair (design D9), copied
 * verbatim from `incident-detail-sections.tsx`'s `DetailField` rather than
 * re-derived — the exact shape section 6 established for any `<dl>`-shaped
 * data pattern in this change.
 */
function DetailField({
  label,
  children,
  mono = true,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-label-caps uppercase text-muted-foreground">
        {label}
      </dt>
      <dd
        className={
          mono
            ? "min-w-0 break-words font-mono text-data-mono text-foreground"
            : "min-w-0 break-words text-body-medium text-foreground"
        }
      >
        {children}
      </dd>
    </div>
  );
}

export function CleanerTaskContextBlock({
  task,
  context,
}: CleanerTaskContextBlockProps) {
  const { t, i18n } = useTranslation("cleaner");
  const locale = i18n.language;
  const empty = t("noRowContext");

  // Compose the postal address, dropping the null fields and the parts that are
  // an empty string. The em-dash renders on its own when EVERY address line is
  // null — a property with no address at all should not paint a stray comma.
  const addressParts = [
    context.addressLine1,
    context.addressLine2,
    context.city,
    context.province,
    context.postalCode,
  ].filter((part): part is string => Boolean(part));
  const address = addressParts.length === 0 ? empty : addressParts.join(", ");

  return (
    <section aria-labelledby="cleaner-context-heading">
      <Card className="flex flex-col gap-3 p-4">
        <h2
          id="cleaner-context-heading"
          className="text-body-lg font-semibold text-foreground"
        >
          {t("context.title")}
        </h2>

        <dl className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <DetailField label={t("context.propertyName")}>
            {context.propertyInternalCode} · {context.propertyName}
          </DetailField>
          <DetailField label={t("context.propertyInternalCode")}>
            {context.propertyInternalCode}
          </DetailField>
          <div className="sm:col-span-2">
            <DetailField label={t("context.address")}>{address}</DetailField>
          </div>
          <DetailField label={t("context.timezone")}>
            {context.timezone}
          </DetailField>
          <DetailField label={t("context.checkoutAt")}>
            {formatDateTime(context.checkoutAt, locale)}
          </DetailField>
          <DetailField label={t("context.nextCheckinDeadline")}>
            {formatDateTime(context.nextCheckinDeadline, locale)}
          </DetailField>
        </dl>
        {/* Reserved for an upcoming task id display; the cleaner cannot see the
            reservation id (no READ_RESERVATIONS), and the task id lives on the
            page heading the orchestrator paints, not here. */}
        <span className="sr-only">{task.id}</span>
      </Card>
    </section>
  );
}