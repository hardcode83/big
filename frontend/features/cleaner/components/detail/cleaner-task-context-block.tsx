"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

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

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex min-w-0 flex-col gap-0.5 ${className ?? ""}`}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-sm font-medium text-foreground">
        {children}
      </span>
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
    <section
      aria-labelledby="cleaner-context-heading"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2
        id="cleaner-context-heading"
        className="text-sm font-semibold text-foreground"
      >
        {t("context.title")}
      </h2>

      <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("context.propertyName")}>
          {context.propertyInternalCode} · {context.propertyName}
        </Field>
        <Field label={t("context.propertyInternalCode")}>
          {context.propertyInternalCode}
        </Field>
        <Field label={t("context.address")} className="sm:col-span-2">
          {address}
        </Field>
        <Field label={t("context.timezone")}>{context.timezone}</Field>
        <Field label={t("context.checkoutAt")}>
          {formatDateTime(context.checkoutAt, locale)}
        </Field>
        <Field label={t("context.nextCheckinDeadline")}>
          {formatDateTime(context.nextCheckinDeadline, locale)}
        </Field>
      </div>
      {/* Reserved for an upcoming task id display; the cleaner cannot see the
          reservation id (no READ_RESERVATIONS), and the task id lives on the
          page heading the orchestrator paints, not here. */}
      <span className="sr-only">{task.id}</span>
    </section>
  );
}