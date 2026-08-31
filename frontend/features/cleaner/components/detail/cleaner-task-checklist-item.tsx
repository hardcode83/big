"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import { useCleanerTaskCycleAction } from "../../hooks/use-cleaner-cycle";
import { mapCleanerError } from "../../lib/error-mapping";
import type { CleaningChecklistItem } from "../../data";

/**
 * The per-item action that ticks a checklist item as done (R4.1, R4.2, R4.3,
 * R4.4).
 *
 * Renders one button per item. The button is only mounted when the parent
 * decides the task is `IN_PROGRESS` (R4.1). It fires `completeChecklistItem`
 * via `useCleanerTaskCycleAction("completeChecklistItem")`, which:
 *
 * - POSTs to `/checklist/{item_id}/complete` with no body (R4.1).
 * - Invalidates `cleanerKeys.checklist(t, id)` on settled (success **and**
 *   failure — R4.4).
 * - Does **not** retry (`retry: false`).
 *
 * Error mapping (R4.3, R4.4):
 * - `404` → the entry silently refreshes the checklist (the item id no longer
 *   belongs to the template) — the inline message key is `notFound` and the
 *   parent view will re-render with the next `data`.
 * - `409` → surface a localized message via `mapCleanerError`, refresh the
 *   task so the UI shows the real status.
 * - Anything else → the generic copy.
 */
export interface CleanerTaskChecklistItemProps {
  taskId: string;
  item: CleaningChecklistItem;
}

export function CleanerTaskChecklistItem({
  taskId,
  item,
}: CleanerTaskChecklistItemProps) {
  const { t } = useTranslation("cleaner");
  const mutation = useCleanerTaskCycleAction("completeChecklistItem");
  const [localError, setLocalError] = useState<string | null>(null);

  if (item.completed) {
    // No button on a completed item — `INSERT ... ON CONFLICT DO UPDATE` is
    // the idempotency, the UI just stops offering the action (R4.2).
    return null;
  }

  function onClick() {
    setLocalError(null);
    mutation.mutate(
      { taskId, itemId: item.itemId },
      {
        onError: (error) => {
          const map = mapCleanerError(error, "completeChecklistItem");
          setLocalError(map.messageKey);
        },
      },
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        variant="outline"
        onClick={onClick}
        disabled={mutation.isPending}
      >
        {mutation.isPending
          ? t("checklist.completing")
          : t("checklist.complete")}
      </Button>
      {localError ? (
        <span role="alert" className="text-xs text-destructive">
          {t(localError)}
        </span>
      ) : null}
    </div>
  );
}