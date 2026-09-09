"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useHasPermission } from "@/lib/auth";
import { cn } from "@/lib/utils";

import type {
  CleanerSummary,
  CleaningTaskListItem,
  CleaningTaskStatus,
  CleaningValidationVerdict,
  PropertySummary,
} from "../data";
import type { Directory, Identity } from "../lib/directory";
import { resolveIdentity } from "../lib/directory";
import { STATUS_BADGE_CLASS, statusColorGroup } from "../lib/task-status";
import { AssignCleanerControl } from "./assign-cleaner-control";
import { ValidateCleaningControl } from "./validate-cleaning-control";

/**
 * R4.1: the cancel control is offered only while the task can still be cancelled —
 * "any live status" the same way the backend's `cancel()` reads `LIVE_STATUSES`, so a
 * task that already finished one way or another (`COMPLETED`, `FAILED`, `CANCELLED`)
 * never shows a button the backend would refuse with `409`.
 */
const TERMINAL_TASK_STATUSES: ReadonlySet<CleaningTaskStatus> = new Set([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);

/**
 * One cleaning task, as a card rather than a table row. Deliberate: R5.2 forbids
 * horizontal page scroll from 320 px, and a table of six columns cannot honour
 * that without one. Each field carries its own label, so the column headings of
 * the `cleaning` namespace still name the data at every width.
 *
 * Nothing here computes business state — the backend owns that
 * (`steering/frontend.md`). The row only renders what the DTO carries and what the
 * two catalogs resolve. The cleaner cell always states the assignment the backend
 * has; the assignment control is added beneath it only when the view offers one AND
 * the role holds `MANAGE_CLEANING_TASKS` (R4.3).
 */
export interface CleaningTaskRowProps {
  /**
   * A **listing** row, so it carries `assignmentBlockedBy` (design D7). The row passes that
   * value straight through to the control and derives nothing from it — which is exactly
   * what keeps "no business logic in components" true here (`steering/frontend.md`, design
   * D9). Deriving it in the client from the property catalog's `current_operational_state`
   * would have meant re-implementing the state machine's matrix on this side.
   */
  task: CleaningTaskListItem;
  properties: Directory<PropertySummary>;
  cleaners: Directory<CleanerSummary>;
  /**
   * Supplied by the view when assignment is on offer. Even then the row hides the
   * control from a role without `MANAGE_CLEANING_TASKS` and keeps the cell as
   * read-only text (R4.3) — the frontend hides, the backend decides.
   */
  assignment?: {
    isPending: boolean;
    isBlocked: boolean;
    onConfirm: (input: { taskId: string; cleanerId: string }) => void;
  };
  /**
   * Supplied by the view when validation is on offer. Same shape and same reasoning as
   * `assignment` above — the row hides `ValidateCleaningControl` from a role without
   * `MANAGE_CLEANING_TASKS` (R5.1), and the control itself hides when `task.status` is not
   * `COMPLETED` (R3.1) — this prop being present is necessary but not sufficient.
   */
  validate?: {
    isPending: boolean;
    isBlocked: boolean;
    onValidate: (input: { taskId: string; verdict: CleaningValidationVerdict }) => void;
  };
  /**
   * Supplied by the view when cancellation is on offer. Same "necessary but not
   * sufficient" shape as `assignment`/`validate` above: the row still hides the
   * control from a role without `MANAGE_CLEANING_TASKS` (R5.1) and from a task whose
   * `status` is already terminal (R4.1). The view owns the dialog's open state and the
   * shared `useCancelCleaningTask()` instance (design D4) — this callback only tells it
   * which row asked.
   */
  cancel?: {
    onOpen: () => void;
    /**
     * Some cancellation — this row's or another's — is in flight against the shared
     * mutation. Disables every row's open button the same way `assignment.isBlocked`
     * does for assignment (fix round, Finding 1, referent D4): the view owns one
     * `CancelCleaningTaskDialog`/mutation pair, so a second row cannot open it while
     * the first is still submitting — that is what would remount the dialog body and
     * clobber the in-flight mutation's state.
     */
    isBlocked: boolean;
  };
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
    <div className={cn("flex min-w-0 flex-col gap-0.5 text-body-base", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-body-medium text-foreground">
        {children}
      </span>
    </div>
  );
}

/**
 * Renders the three degraded shapes of design D5 and never the raw id. `pending`
 * shows a neutral marker with no identity text — an announced one, so a screen
 * reader is not left with a bare dash.
 */
function IdentityValue<T>({
  identity,
  render,
}: {
  identity: Identity<T>;
  render: (value: T) => ReactNode;
}) {
  const { t } = useTranslation("cleaning");
  switch (identity.kind) {
    case "unassigned":
      return (
        <span className="text-muted-foreground">{t("identity.unassigned")}</span>
      );
    case "pending":
      return (
        <>
          <span aria-hidden="true" className="text-muted-foreground">
            —
          </span>
          <span className="sr-only">{t("identity.loading")}</span>
        </>
      );
    case "unavailable":
      return (
        <span className="italic text-muted-foreground">
          {t("identity.unavailable")}
        </span>
      );
    case "resolved":
      return <>{render(identity.value)}</>;
  }
}

export function CleaningTaskRow({
  task,
  properties,
  cleaners,
  assignment,
  validate,
  cancel,
}: CleaningTaskRowProps) {
  const { t, i18n } = useTranslation("cleaning");
  const canManage = useHasPermission("MANAGE_CLEANING_TASKS");
  const locale = i18n.language;
  const headingId = `cleaning-task-${task.id}`;

  const property = resolveIdentity(task.propertyId, properties);
  const cleaner = resolveIdentity(task.assignedCleanerId, cleaners);

  const formatDate = (iso: string | null): ReactNode =>
    iso === null ? (
      <span className="text-muted-foreground">{t("identity.notScheduled")}</span>
    ) : (
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(iso))
    );

  return (
    <li aria-labelledby={headingId} className="min-w-0 list-none">
      <Card className="flex min-w-0 flex-col gap-3 p-4">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <h3
          id={headingId}
          className="min-w-0 flex-1 break-words text-body-lg font-semibold text-foreground"
        >
          <span className="sr-only">{t("columns.property")}: </span>
          <IdentityValue
            identity={property}
            render={(value) =>
              `${value.internalCode} ${t("separator")} ${value.name}`
            }
          />
        </h3>
        <Badge
          variant="outline"
          className={cn(STATUS_BADGE_CLASS[statusColorGroup(task.status)])}
        >
          <span className="sr-only">{t("columns.status")}: </span>
          {t(`status.${task.status}`)}
        </Badge>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("columns.cleaner")} className="sm:col-span-2">
          {/*
            The resolved identity is shown for EVERY role, control or not. It is the
            row's single statement of who the backend currently has assigned, so a
            manager can read the current cleaner while choosing a new one, and a
            rejected write (R4.4) leaves a truthful cell behind rather than the pick
            the server refused. The control below it only proposes.
          */}
          <IdentityValue identity={cleaner} render={(value) => value.name} />
          {assignment && canManage ? (
            <AssignCleanerControl
              taskId={task.id}
              currentCleanerId={task.assignedCleanerId}
              cleaners={Array.from(cleaners.index.values())}
              isPending={assignment.isPending}
              isBlocked={assignment.isBlocked}
              blockedBy={task.assignmentBlockedBy}
              onConfirm={assignment.onConfirm}
            />
          ) : null}
        </Field>
        <Field label={t("columns.scheduledStart")}>
          {formatDate(task.scheduledStart)}
        </Field>
        <Field label={t("columns.scheduledEnd")}>
          {formatDate(task.scheduledEnd)}
        </Field>
        <Field label={t("columns.createdAt")} className="sm:col-span-2">
          {formatDate(task.createdAt)}
        </Field>
        {/*
          Painted once the task has ever been completed or already carries a verdict
          (design D7) — never for a task nobody has cleaned yet, where "Pending
          validation" would read as stuck. Shown to EVERY role, control or not
          (R5.2): the verdict is data the backend already publishes, not a permission.
        */}
        {task.completedAt !== null || task.validationStatus !== "PENDING" ? (
          <>
            <Field label={t("columns.completedAt")}>
              {formatDate(task.completedAt)}
            </Field>
            <Field label={t("columns.validation")} className="sm:col-span-2">
              {t(`validation.${task.validationStatus}`)}
              {task.validatedAt !== null ? (
                <span className="block text-muted-foreground">
                  {formatDate(task.validatedAt)}
                </span>
              ) : null}
              {validate && canManage ? (
                <ValidateCleaningControl
                  taskId={task.id}
                  status={task.status}
                  validationStatus={task.validationStatus}
                  isPending={validate.isPending}
                  isBlocked={validate.isBlocked}
                  onValidate={validate.onValidate}
                />
              ) : null}
            </Field>
          </>
        ) : null}
      </div>
      {/*
        R4.1: offered only for a live task and only to a manager (R5.1) — same
        `canManage` gate as assignment and validation above, plus the terminal-status
        check this control alone needs. Opening the dialog is all this button does;
        the mutation and the reason form live in `CancelCleaningTaskDialog`, owned by
        the view (design D4).
      */}
      {cancel && canManage && !TERMINAL_TASK_STATUSES.has(task.status) ? (
        <div className="flex justify-end">
          <Button
            type="button"
            variant="outline"
            disabled={cancel.isBlocked}
            onClick={cancel.onOpen}
          >
            {t("cancel.open")}
          </Button>
        </div>
      ) : null}
      </Card>
    </li>
  );
}
