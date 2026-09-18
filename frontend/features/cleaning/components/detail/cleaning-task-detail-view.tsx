"use client";

import Link from "next/link";
import { useCallback, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useHasPermission } from "@/lib/auth";

import type {
  CleanerSummary,
  CleaningTask,
  CleaningTaskListItem,
} from "../../data";
import { assignErrorKey } from "../../lib/assign-error";
import { buildDirectory } from "../../lib/directory";
import { mapCleaningDetailError } from "../../lib/detail-error";
import {
  GENERIC_VALIDATE_ERROR_KEY,
  VALIDATE_ERROR_TABLE,
  keyForStatus,
} from "../../lib/manage-error";
import { useCleaningTask } from "../../hooks/use-cleaning-task";
import { useAssignCleaningTask } from "../../hooks/use-assign-cleaning-task";
import { useCancelCleaningTask } from "../../hooks/use-cancel-cleaning-task";
import {
  useCleanerDirectory,
  usePropertyDirectory,
} from "../../hooks/use-cleaning-data";
import { useValidateCleaningTask } from "../../hooks/use-validate-cleaning-task";
import { DetailAssignedCleanerBlock } from "./detail-assigned-cleaner-block";
import { DetailContextLinksBlock } from "./detail-context-links-block";
import { DetailHeaderBlock } from "./detail-header-block";
import { DetailIdentifyingBlock } from "./detail-identifying-block";
import { DetailManagerActionsBlock } from "./detail-manager-actions-block";
import { ManagerCleaningTaskMessagesPanel } from "./manager-cleaning-task-messages-panel";
import { ManagerCleaningTaskTabs } from "./manager-cleaning-task-tabs";

/**
 * The detail view for `/cleaning/[id]` (proposal R1-R6, design D1/D6/D7/D8).
 *
 * Composes six blocks of reading (header / identifying / assigned cleaner /
 * context links / manager actions / metadata is folded into the header
 * here — proposal R2 collapses completed/validated into the lifecycle row
 * inside the header, D1's block decomposition keeps that as the header
 * block alone). The single live region lives here, fed by the three
 * manager mutations (R5.5 — the precedent of `cleaning-manager-view` D11
 * + `cleaning-task-manage-web` D4/D11).
 *
 * `canManage` gates the manager-actions block (R5.1, same gate the listing
 * uses). `canReadProperties` and `canReadReservations` gate the two
 * cross-resource links (R4.1/R4.3, `lib/auth/permissions.ts` grants them
 * to the two workspace roles only).
 *
 * **No header sticky.** D8 mirrors `IncidentDetailView`'s
 * `features/incidents/components/detail/incident-detail-view.tsx:84-92`
 * (the precedent already in production).
 *
 * **No `RoutePlaceholder`**. The page registered at section 5
 * (`frontend/app/(workspace)/cleaning/[id]/page.tsx`) is the real mount,
 * not a placeholder — the loading state paints `LoadingState` (R1.3),
 * the `not-found` state paints `EmptyState` (R1.2), and the error state
 * emits an `ErrorState` with `role="alert"` (R1.4).
 */
export function CleaningTaskDetailView({ taskId }: { taskId: string }) {
  const { t } = useTranslation("cleaning");
  const { t: tStates } = useTranslation("states");
  const query = useCleaningTask(taskId);
  const state = mapCleaningDetailError(query, () => {
    void query.refetch();
  });
  const propertyDirectory = usePropertyDirectory();
  const cleanerDirectory = useCleanerDirectory();
  const canManage = useHasPermission("MANAGE_CLEANING_TASKS");
  const canReadProperties = useHasPermission("READ_PROPERTIES");
  const canReadReservations = useHasPermission("READ_RESERVATIONS");
  // The three manager mutations — the view owns each one so the live
  // region below can read the result of whichever of them lands first
  // (R5.5, D7). `cancel` shares the same `useCancelCleaningTask` instance
  // the dialog consumes, the same shared-instance pattern `cleaning-view.tsx`
  // uses (D-cleaning-task-manage D4).
  const assign = useAssignCleaningTask();
  const validate = useValidateCleaningTask();
  const cancel = useCancelCleaningTask();
  const [cancelOpen, setCancelOpen] = useState(false);

  // Sticky: once the messages read 404s the task is gone, and it does not
  // come back by refetching the task query. `useLayoutEffect` (in the panel)
  // fires before the browser paints, so this flag flips in the same frame
  // the panel returns `null` for — same convention `ManagerIncidentDetailView`
  // uses (section 2, R1.5).
  const [messagesNotFound, setMessagesNotFound] = useState(false);
  const onMessagesNotFound = useCallback(
    () => setMessagesNotFound(true),
    [],
  );

  if (state.kind === "loading") {
    return (
      <LoadingState label={tStates("loading.label")} className="p-4" />
    );
  }
  if (state.kind === "forbidden") {
    return (
      <p className="p-4 text-body-base text-muted-foreground">
        {t("detail.forbidden")}
      </p>
    );
  }
  if (state.kind === "not-found" || messagesNotFound) {
    return (
      <section className="flex flex-col gap-2 p-4">
        <EmptyState
          title={t("detail.notFound")}
          action={
            <Link
              href="/cleaning"
              className="text-body-base text-primary underline-offset-4 hover:underline"
            >
              {t("detail.context.backToList")}
            </Link>
          }
        />
      </section>
    );
  }
  if (state.kind === "validation") {
    return (
      <p className="p-4 text-body-base text-muted-foreground">
        {t("detail.validation")}
      </p>
    );
  }
  if (state.kind === "error") {
    return (
      <ErrorState
        className="p-4"
        title={t("detail.error.title")}
        description={t("detail.error.description")}
        onRetry={() => state.refetch()}
        retryLabel={t("detail.error.retry")}
      />
    );
  }

  const task = state.data;
  const properties = {
    index: buildDirectory(propertyDirectory.data),
    isPending: propertyDirectory.isPending,
  };
  const cleaners = {
    index: buildDirectory(cleanerDirectory.data),
    isPending: cleanerDirectory.isPending,
  };

  function announcement(): ReactNode {
    const source = pickAnnouncementSource([
      {
        kind: "assign",
        isPending: assign.isPending,
        isError: assign.isError,
        isSuccess: assign.isSuccess,
        submittedAt: assign.submittedAt,
      },
      {
        kind: "validate",
        isPending: validate.isPending,
        isError: validate.isError,
        isSuccess: validate.isSuccess,
        submittedAt: validate.submittedAt,
      },
      {
        kind: "cancel",
        isPending: cancel.isPending,
        isError: false,
        isSuccess: cancel.isSuccess,
        submittedAt: cancel.submittedAt,
      },
    ]);
    if (source === null) {
      return null;
    }
    if (source.kind === "cancel") {
      return t(source.via === "pending" ? "cancel.sending" : "cancel.success");
    }
    if (source.kind === "validate") {
      if (source.via === "pending") {
        return t("validate.sending");
      }
      if (source.via === "error") {
        return (
          <span role="alert">
            {t(
              keyForStatus(
                validate.error,
                VALIDATE_ERROR_TABLE,
                GENERIC_VALIDATE_ERROR_KEY,
              ),
            )}
          </span>
        );
      }
      return t(
        validate.data?.validationStatus === "FAILED"
          ? "validate.success.failed"
          : "validate.success.passed",
      );
    }
    // source.kind === "assign"
    if (source.via === "pending") {
      return t("assign.sending");
    }
    if (source.via === "error") {
      return <span role="alert">{t(assignErrorKey(assign.error))}</span>;
    }
    const assigned = resolveCleanerName(assign.data, cleaners);
    return t("assign.success", {
      name: assigned ?? t("identity.unavailable"),
    });
  }

  return (
    <article
      aria-labelledby="cleaning-task-heading"
      className="flex flex-col gap-4 p-4"
    >
      <div className="flex items-center gap-3">
        <h1
          id="cleaning-task-heading"
          className="text-xl font-semibold text-foreground"
        >
          {t("detail.title")}
        </h1>
        <Link
          href="/cleaning"
          className="text-body-base text-primary underline-offset-4 hover:underline"
        >
          {t("detail.context.backToList")}
        </Link>
      </div>
      {/*
        The single live region of design D7 / proposal R5.5. The page mounts
        it before the first mutation lands so a screen reader is already
        observing it when the result arrives. `announcement()` picks which
        mutation gets to speak, exactly the same precedence the listing
        declares in its `pickAnnouncementSource` (`cleaning-view.tsx:70-88`).
        D6 of `staff-messaging-manager-view` keeps this region here in the
        wrapper — the architect review of 2026-09-18 measured that separation
        in `cleaning-manager-task-detail` D7, and moving it into the tabs
        or the messages panel would break R5.5 (live region observable to
        the manager).
      */}
      <div
        role="status"
        aria-live="polite"
        className="text-body-base text-muted-foreground empty:hidden"
      >
        {announcement()}
      </div>
      {/*
        Structural refactor of `staff-messaging-manager-view` D6: the
        operational content passes through `ManagerCleaningTaskTabs` so the
        messages tab can mount alongside it, but the six reading blocks and
        the cancel dialog stay in the same order with the same props. Both
        tabs stay mounted (D4) so the cancel sheet's `open` state survives
        a round trip through the messages tab.
      */}
      <ManagerCleaningTaskTabs
        content={
          <div className="flex flex-col gap-4">
            <DetailHeaderBlock
              status={task.status}
              validationStatus={task.validationStatus}
              scheduledStart={task.scheduledStart}
              scheduledEnd={task.scheduledEnd}
              completedAt={task.completedAt}
              validatedAt={task.validatedAt}
            />
            <DetailIdentifyingBlock
              propertyId={task.propertyId}
              reservationId={task.reservationId}
              properties={properties}
            />
            <DetailAssignedCleanerBlock
              assignedCleanerId={task.assignedCleanerId}
              cleaners={cleaners}
            />
            {canManage ? (
              <DetailManagerActionsBlock
                task={task}
                assignment={{
                  isPending: assign.isPending,
                  // The view owns one mutation; a second `mutate` would detach the
                  // first and lose its rejection, which R5.4 makes mandatory, so the
                  // confirm button is unreachable until the first settles.
                  isBlocked: assign.isPending,
                  onConfirm: assign.mutate,
                }}
                validate={{
                  isPending: validate.isPending,
                  isBlocked: validate.isPending,
                  onValidate: validate.mutate,
                }}
                cancel={{
                  open: cancelOpen,
                  onOpenChange: setCancelOpen,
                  mutation: cancel,
                }}
                cleaners={Array.from(cleaners.index.values())}
              />
            ) : null}
            <DetailContextLinksBlock
              propertyId={task.propertyId}
              reservationId={task.reservationId}
              canReadProperties={canReadProperties}
              canReadReservations={canReadReservations}
            />
          </div>
        }
        renderMessages={(enabled) => (
          <ManagerCleaningTaskMessagesPanel
            taskId={task.id}
            enabled={enabled}
            onNotFound={onMessagesNotFound}
          />
        )}
      />
    </article>
  );
}

interface AnnouncementSource {
  kind: string;
  isPending: boolean;
  isError: boolean;
  isSuccess: boolean;
  submittedAt: number;
}

function pickAnnouncementSource(
  sources: readonly AnnouncementSource[],
): { kind: string; via: "pending" | "error" | "success" } | null {
  const pending = sources.find((source) => source.isPending);
  if (pending) {
    return { kind: pending.kind, via: "pending" };
  }
  const errored = sources.filter((source) => source.isError);
  if (errored.length > 0) {
    const latest = errored.reduce((a, b) =>
      b.submittedAt > a.submittedAt ? b : a,
    );
    return { kind: latest.kind, via: "error" };
  }
  const succeeded = sources.filter((source) => source.isSuccess);
  if (succeeded.length > 0) {
    const latest = succeeded.reduce((a, b) =>
      b.submittedAt > a.submittedAt ? b : a,
    );
    return { kind: latest.kind, via: "success" };
  }
  return null;
}

function resolveCleanerName(
  task: CleaningTask | CleaningTaskListItem | undefined,
  cleaners: { index: ReadonlyMap<string, CleanerSummary> },
): string | null {
  if (!task) {
    return null;
  }
  const cleaner =
    task.assignedCleanerId !== null
      ? cleaners.index.get(task.assignedCleanerId)
      : undefined;
  return cleaner ? cleaner.name : null;
}