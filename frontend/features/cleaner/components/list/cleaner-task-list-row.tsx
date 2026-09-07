"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { CleaningTaskContext, CleaningTaskListItem } from "../../data";
import { formatDateTime } from "../../lib/format";
import { STATUS_BADGE_CLASS, statusColorGroup } from "@/features/cleaning";

/**
 * One cleaning task, as a card (D15). Each field carries its own label so the
 * column headings stay legible at every width.
 *
 * The context may be `null` if the row's `GET /context` failed (D4): the row
 * still renders, with the property name and code replaced by the em-dash `—`
 * (R1.4). The error message that would have been rendered never reaches the
 * row — the list's `ErrorState` is reserved for the **list** query failing.
 */
export interface CleanerTaskListRowProps {
  task: CleaningTaskListItem;
  context: CleaningTaskContext | null;
}

export function CleanerTaskListRow({ task, context }: CleanerTaskListRowProps) {
  const { t, i18n } = useTranslation(["cleaner", "cleaning"]);
  const locale = i18n.language;
  const headingId = `cleaner-task-${task.id}`;

  const propertyName =
    context === null
      ? t("cleaner:noRowContext")
      : `${context.propertyInternalCode} · ${context.propertyName}`;
  const checkoutAt =
    context === null
      ? t("cleaner:noRowContext")
      : formatDateTime(context.checkoutAt, locale);
  const nextDeadline =
    context === null
      ? t("cleaner:noRowContext")
      : formatDateTime(context.nextCheckinDeadline, locale);

  return (
    <li aria-labelledby={headingId} className="list-none">
      <Card className="p-4">
        <Link
          href={`/cleaner/tasks/${task.id}`}
          className="flex min-w-0 flex-col gap-3"
        >
          <div className="flex min-w-0 items-start justify-between gap-3">
            <h3
              id={headingId}
              className="min-w-0 flex-1 break-words text-body-lg font-semibold text-foreground"
            >
              <span className="sr-only">{t("cleaner:list.label")}: </span>
              {propertyName}
            </h3>
            <Badge
              variant="outline"
              className={cn(STATUS_BADGE_CLASS[statusColorGroup(task.status)])}
            >
              <span className="sr-only">{t("cleaning:columns.status")}: </span>
              {t(`cleaning:status.${task.status}`)}
            </Badge>
          </div>

          <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-body-base text-muted-foreground">
                {t("cleaner:context.checkoutAt")}
              </span>
              <span className="min-w-0 break-words text-body-medium text-foreground">
                {checkoutAt}
              </span>
            </div>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-body-base text-muted-foreground">
                {t("cleaner:context.nextCheckinDeadline")}
              </span>
              <span className="min-w-0 break-words text-body-medium text-foreground">
                {nextDeadline}
              </span>
            </div>
          </div>
        </Link>
      </Card>
    </li>
  );
}