"use client";

import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type {
  CleaningTask,
  CleaningTaskStatus,
  CleaningValidationStatus,
  IsoDateTime,
} from "../../data";
import { STATUS_BADGE_CLASS, statusColorGroup } from "../../lib/task-status";

/**
 * One labelled field inside the header block. Same shape `DetailField` has in
 * the incidents section file (`features/incidents/components/detail/incident-detail-sections.tsx`):
 * an uppercase muted label, a value in body type underneath.
 */
function HeaderField({
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

function formatDateTime(value: IsoDateTime | null, locale: string): string {
  if (value === null) {
    return "—";
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

/**
 * The header section of `/cleaning/[id]` (proposal R2.1-R2.3, design D8).
 *
 * Carries four pieces of state in one block:
 *
 * - the task's `CleaningTaskStatus`, badge-coloured by `statusColorGroup`
 *   (the exact map the listing already uses, R1.6 / D-cleaning-task-manager-view).
 * - the task's `validationStatus`, painted as the bare label (R2.1 — no
 *   decoration, the verdict is data the backend already publishes).
 * - the scheduled window `scheduledStart`–`scheduledEnd`, rendered with
 *   `Intl.DateTimeFormat` — the same call the listing's row uses for the
 *   individual columns (R2.1, copy local while the
 *   `shared-datetime-formatter` entry is pending).
 * - `completedAt` and `validatedAt`, only when `completedAt !== null` OR
 *   `validationStatus !== "PENDING"` (R2.2 — never for a task nobody has
 *   cleaned yet, where "Pendiente de validación" would read as stuck).
 *
 * The locale comes from `i18n.language`; the suite already exercises `es`,
 * which is what `cleaning-task-row.tsx` does for its columns. Empty values
 * fall back to a dash, never a blank cell.
 */
export interface DetailHeaderBlockProps {
  status: CleaningTaskStatus;
  validationStatus: CleaningValidationStatus;
  scheduledStart: IsoDateTime | null;
  scheduledEnd: IsoDateTime | null;
  completedAt: IsoDateTime | null;
  validatedAt: IsoDateTime | null;
}

export function DetailHeaderBlock({
  status,
  validationStatus,
  scheduledStart,
  scheduledEnd,
  completedAt,
  validatedAt,
}: DetailHeaderBlockProps) {
  const { t, i18n } = useTranslation("cleaning");
  const locale = i18n.language;
  const showLifecycle = completedAt !== null || validationStatus !== "PENDING";

  return (
    <header className="flex flex-col gap-3 border-b border-border pb-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-label-caps uppercase text-muted-foreground">
            {t("detail.header.status")}
          </span>
          <Badge
            variant="outline"
            className={cn("self-start", STATUS_BADGE_CLASS[statusColorGroup(status)])}
          >
            {t(`status.${status}`)}
          </Badge>
        </div>
        <HeaderField label={t("detail.header.validation")}>
          {t(`validation.${validationStatus}`)}
        </HeaderField>
      </div>
      <HeaderField label={t("detail.header.scheduledWindow")}>
        {t("detail.header.scheduledWindowValue", {
          start: formatDateTime(scheduledStart, locale),
          end: formatDateTime(scheduledEnd, locale),
        })}
      </HeaderField>
      {showLifecycle ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <HeaderField label={t("detail.header.completedAt")}>
            {formatDateTime(completedAt, locale)}
          </HeaderField>
          {validatedAt !== null ? (
            <HeaderField label={t("detail.header.validatedAt")}>
              {formatDateTime(validatedAt, locale)}
            </HeaderField>
          ) : null}
        </div>
      ) : null}
    </header>
  );
}

/**
 * Re-export of the type narrowed to the relevant fields. Used by the view
 * composition to satisfy `Pick<CleaningTask, ...>` without repeating the
 * property list twice (the props list above and the public type).
 */
export type DetailHeaderBlockTask = Pick<
  CleaningTask,
  | "status"
  | "validationStatus"
  | "scheduledStart"
  | "scheduledEnd"
  | "completedAt"
  | "validatedAt"
>;