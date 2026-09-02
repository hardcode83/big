"use client";

import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/states";

import type { CleaningChecklist } from "../../data";

/**
 * The checklist block (R2.3, R4.1). Renders every item in the backend's
 * order, with the `required` marker and the completion state (`pending` /
 * `completed_at` + `completed_by`).
 *
 * This component is the read-only half. Section 6 swaps in a per-item control
 * that mounts `useCleanerTaskCycleAction("completeChecklistItem")` and is
 * gated by `task.status === "IN_PROGRESS"`.
 */
export interface CleanerTaskChecklistProps {
  checklist: CleaningChecklist;
  /**
   * When `true`, each item exposes a per-item action (mounted by section 6's
   * mutation component). When `false`, the items are read-only — used in any
   * status other than `IN_PROGRESS`.
   */
  interactive: boolean;
  /**
   * Slot for the per-item action. The shell renders one row per item; when
   * `interactive` is `false` the slot is `null`. Section 6 wraps the
   * component above to thread the action button through.
   */
  renderItemAction?: (item: CleaningChecklist["data"][number]) => React.ReactNode;
}

export function CleanerTaskChecklist({
  checklist,
  interactive,
  renderItemAction,
}: CleanerTaskChecklistProps) {
  const { t } = useTranslation(["cleaner", "states"]);

  if (checklist.data.length === 0) {
    return (
      <section
        aria-labelledby="cleaner-checklist-heading"
        className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
      >
        <h2
          id="cleaner-checklist-heading"
          className="text-sm font-semibold text-foreground"
        >
          {t("cleaner:checklist.title")}
        </h2>
        <EmptyState
          title={t("cleaner:checklist.empty.title")}
          description={t("cleaner:checklist.empty.description")}
        />
      </section>
    );
  }

  return (
    <section
      aria-labelledby="cleaner-checklist-heading"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2
        id="cleaner-checklist-heading"
        className="text-sm font-semibold text-foreground"
      >
        {t("cleaner:checklist.title")}
      </h2>
      <ul aria-label={t("cleaner:checklist.title")} className="flex flex-col gap-2">
        {checklist.data.map((item) => {
          const completed = item.completed;
          return (
            <li
              key={item.itemId}
              className="flex min-w-0 items-start justify-between gap-3 rounded-md border bg-background p-3"
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-medium text-foreground">
                  {item.label}
                  {item.required ? (
                    <span className="ml-2 text-xs font-medium text-destructive">
                      {t("cleaner:checklist.required")}
                    </span>
                  ) : null}
                </span>
                {completed && item.completedAt ? (
                  <span className="text-xs text-muted-foreground">
                    {t("cleaner:checklist.completed")}{" "}
                    {t("cleaner:checklist.completedBy")} {item.completedBy ?? "—"}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {t("cleaner:checklist.pending")}
                  </span>
                )}
              </div>
              {interactive && renderItemAction ? renderItemAction(item) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}