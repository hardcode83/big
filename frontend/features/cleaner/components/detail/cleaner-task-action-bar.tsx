"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";

import {
  useCleanerTaskCycleAction,
  useCompleteCleaningTask,
  useRejectCleaningTask,
} from "../../hooks/use-cleaner-cycle";
import type {
  CleaningChecklist,
  CleaningTask,
  PhotoRequirementsResponse,
} from "../../data";
import {
  conflictReason,
  hasMissingRequiredItems,
  hasMissingRequiredPhotos,
} from "../../lib/conflict-reason";
import { mapCleanerError } from "../../lib/error-mapping";
import {
  cleanerActions,
  cleanerNoActionReason,
} from "../../lib/cleaner-actions";
import { CleanerIncidentReportPanel } from "./cleaner-incident-report-panel";

/**
 * The action bar at the end of the detail view flow (R3.1, R6.1, R7.1, R8.4,
 * D15).
 *
 * Reads `CLEANER_ACTIONS[task.status]` and renders the corresponding buttons
 * with the `cleaning:status.*` palette. For `IN_PROGRESS` it also surfaces the
 * «Reportar incidencia» trigger (R6.1) and «Cerrar limpieza» (R7.1). For
 * statuses with no actions, the bar shows the localized
 * `cleanerNoActionReason(status)` explanation (R3.1).
 *
 * On a `409` it shows the reason `conflictReason` derives from the **refreshed**
 * checklist and requirements — the three refusals share `code: "CONFLICT"`
 * and differ only in an English message, which R7.3 forbids rendering — and
 * it does not retry.
 */
export interface CleanerTaskActionBarProps {
  task: CleaningTask;
  checklist: CleaningChecklist;
  requirements: PhotoRequirementsResponse;
}

export function CleanerTaskActionBar({
  task,
  checklist,
  requirements,
}: CleanerTaskActionBarProps) {
  const { t } = useTranslation(["cleaner", "cleaning"]);
  const router = useRouter();
  const [localError, setLocalError] = useState<string | null>(null);
  const [highlightItems, setHighlightItems] = useState<boolean>(false);
  const [highlightPhotos, setHighlightPhotos] = useState<boolean>(false);

  const accept = useCleanerTaskCycleAction("accept");
  const start = useCleanerTaskCycleAction("start");
  const reject = useRejectCleaningTask({
    onRejected: () => router.replace("/cleaner"),
  });
  const complete = useCompleteCleaningTask({
    onCompleted: () => router.replace("/cleaner"),
  });

  const actions = cleanerActions(task.status);
  const isInProgress = task.status === "IN_PROGRESS";

  function messageFor(error: Error | null): string | null {
    if (!error) return null;
    if (error instanceof ApiError && error.status === 409) {
      // The three-clause refusal of the close — read from the refreshed state
      // (D7, R7.3).
      if (error === complete.error) {
        const reason = conflictReason(checklist, requirements);
        setHighlightItems(hasMissingRequiredItems(checklist));
        setHighlightPhotos(hasMissingRequiredPhotos(requirements));
        return t(`cleaner:complete.errors.${reason}`);
      }
      return t("cleaner:actions.errors.conflict");
    }
    return t("cleaner:actions.errors.generic");
  }

  if (actions.length === 0) {
    return (
      <section
        aria-labelledby="cleaner-action-bar-heading"
        className="flex flex-col gap-2 rounded-lg border bg-surface p-4"
      >
        <h2
          id="cleaner-action-bar-heading"
          className="text-sm font-semibold text-foreground"
        >
          {t("cleaner:actions.title")}
        </h2>
        {localError ? (
          <p role="alert" className="text-sm text-destructive">
            {localError}
          </p>
        ) : null}
        <p className="text-sm text-muted-foreground">
          {t(`cleaner:actions.none.${cleanerNoActionReason(task.status)}`)}
        </p>
      </section>
    );
  }

  // Exported so section 10's detail view can read it — keeps the highlighted
  // pass-through to the checklist/photos blocks in one place.
  void highlightItems;
  void highlightPhotos;

  return (
    <section
      aria-labelledby="cleaner-action-bar-heading"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2
        id="cleaner-action-bar-heading"
        className="text-sm font-semibold text-foreground"
      >
        {t("cleaner:actions.title")}
      </h2>

      <div className="flex flex-wrap gap-2">
        {actions.includes("accept") ? (
          <Button
            type="button"
            disabled={accept.isPending}
            onClick={() => {
              setLocalError(null);
              accept.mutate(
                { taskId: task.id },
                {
                  onError: (error) => {
                    setLocalError(messageFor(error));
                  },
                },
              );
            }}
          >
            {t("cleaner:actions.accept")}
          </Button>
        ) : null}
        {actions.includes("reject") ? (
          <Button
            type="button"
            variant="outline"
            disabled={reject.isPending}
            onClick={() => {
              setLocalError(null);
              reject.mutate(
                { taskId: task.id },
                {
                  onError: (error) => {
                    setLocalError(messageFor(error));
                  },
                },
              );
            }}
          >
            {t("cleaner:actions.reject")}
          </Button>
        ) : null}
        {actions.includes("start") ? (
          <Button
            type="button"
            disabled={start.isPending}
            onClick={() => {
              setLocalError(null);
              start.mutate(
                { taskId: task.id },
                {
                  onError: (error) => {
                    setLocalError(messageFor(error));
                  },
                },
              );
            }}
          >
            {t("cleaner:actions.start")}
          </Button>
        ) : null}
        {actions.includes("complete") ? (
          <Button
            type="button"
            disabled={complete.isPending}
            onClick={() => {
              setLocalError(null);
              setHighlightItems(false);
              setHighlightPhotos(false);
              complete.mutate(
                { taskId: task.id },
                {
                  onError: (error) => {
                    setLocalError(messageFor(error));
                  },
                },
              );
            }}
          >
            {t("cleaner:actions.complete")}
          </Button>
        ) : null}
      </div>

      {isInProgress ? (
        <CleanerIncidentReportPanel taskId={task.id} status={task.status} />
      ) : null}

      {localError ? (
        <p role="alert" className="text-sm text-destructive">
          {localError}
        </p>
      ) : null}
    </section>
  );
}