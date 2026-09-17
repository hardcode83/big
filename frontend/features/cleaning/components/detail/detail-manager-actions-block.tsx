"use client";

import type { UseMutationResult } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  CleanerSummary,
  CleaningTask,
  CleaningValidationVerdict,
} from "../../data";
import type { CancelCleaningTaskInput } from "../../hooks/use-cancel-cleaning-task";
import { AssignCleanerControl } from "../assign-cleaner-control";
import { CancelCleaningTaskDialog } from "../cancel-cleaning-task-dialog";
import { ValidateCleaningControl } from "../validate-cleaning-control";

/**
 * The three manager controls of `/cleaning/[id]` — assign / validate / cancel
 * (proposal R5.1/R5.2/R5.3, design D7). Mounted by the view **only** when
 * `MANAGE_CLEANING_TASKS` is held.
 *
 * The view owns all three mutation instances (R5.5 — the live region has to
 * read them). This block receives them by props and renders the three
 * existing controls with the exact props the listing already uses
 * (`cleaning-task-row.tsx:222` and following for assign / validate, and the
 * shared `CancelCleaningTaskDialog` for cancel).
 *
 * **No `*Detail` variants.** D7 forbids them: duplicating surface
 * duplicates the bug surface and the divergence surface (R5.2). The
 * proposal names this rule explicitly.
 */
export interface DetailManagerActionsBlockProps {
  task: CleaningTask;
  assignment: {
    isPending: boolean;
    isBlocked: boolean;
    onConfirm: (input: { taskId: string; cleanerId: string }) => void;
  };
  validate: {
    isPending: boolean;
    isBlocked: boolean;
    onValidate: (input: {
      taskId: string;
      verdict: CleaningValidationVerdict;
    }) => void;
  };
  cancel: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    mutation: UseMutationResult<
      CleaningTask,
      Error,
      CancelCleaningTaskInput
    >;
  };
  cleaners: ReadonlyArray<CleanerSummary>;
}

export function DetailManagerActionsBlock({
  task,
  assignment,
  validate,
  cancel,
  cleaners,
}: DetailManagerActionsBlockProps) {
  const { t } = useTranslation("cleaning");
  return (
    <section
      aria-label={t("detail.manager.title")}
      className="flex flex-col gap-4 border-b border-border py-4"
    >
      <h2 className="text-body-lg font-semibold text-foreground">
        {t("detail.manager.title")}
      </h2>
      <div className="flex flex-col gap-4">
        <AssignCleanerControl
          taskId={task.id}
          currentCleanerId={task.assignedCleanerId}
          cleaners={cleaners}
          isPending={assignment.isPending}
          isBlocked={assignment.isBlocked}
          blockedBy={null}
          onConfirm={assignment.onConfirm}
        />
        <ValidateCleaningControl
          taskId={task.id}
          status={task.status}
          validationStatus={task.validationStatus}
          isPending={validate.isPending}
          isBlocked={validate.isBlocked}
          onValidate={validate.onValidate}
        />
        <div className="flex justify-end">
          {/*
            The cancel button is the same shape as the listing's
            (`cleaning-task-row.tsx:281-292`): outline button, hidden when
            the task is already terminal (R4.1), disabled while a
            cancellation is in flight. The dialog the button opens is
            rendered below — one dialog for the page, no `*Detail` variant.
          */}
          <CancelOpenButton
            taskId={task.id}
            onOpen={() => cancel.onOpenChange(true)}
            isPending={cancel.mutation.isPending}
            isLive={!isTerminal(task.status)}
          />
        </div>
      </div>
      <CancelCleaningTaskDialog
        open={cancel.open}
        onOpenChange={cancel.onOpenChange}
        taskId={task.id}
        mutation={cancel.mutation}
      />
    </section>
  );
}

const TERMINAL_STATUSES: ReadonlySet<CleaningTask["status"]> = new Set([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);

function isTerminal(status: CleaningTask["status"]): boolean {
  return TERMINAL_STATUSES.has(status);
}

function CancelOpenButton({
  onOpen,
  isPending,
  isLive,
}: {
  taskId: string;
  onOpen: () => void;
  isPending: boolean;
  isLive: boolean;
}) {
  const { t } = useTranslation("cleaning");
  if (!isLive) {
    return null;
  }
  return (
    <button
      type="button"
      className="tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground"
      disabled={isPending}
      onClick={onOpen}
    >
      {t("cancel.open")}
    </button>
  );
}