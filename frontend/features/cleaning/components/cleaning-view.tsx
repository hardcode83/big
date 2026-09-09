"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useAuth, useHasPermission } from "@/lib/auth";

import { useAssignCleaningTask } from "../hooks/use-assign-cleaning-task";
import { useCancelCleaningTask } from "../hooks/use-cancel-cleaning-task";
import { useCreateCleaningTask } from "../hooks/use-create-cleaning-task";
import {
  useCleanerDirectory,
  useCleaningTasks,
  usePropertyDirectory,
} from "../hooks/use-cleaning-data";
import { useValidateCleaningTask } from "../hooks/use-validate-cleaning-task";
import { assignErrorKey } from "../lib/assign-error";
import { buildDirectory, resolveIdentity } from "../lib/directory";
import {
  CREATE_ERROR_TABLE,
  GENERIC_CREATE_ERROR_KEY,
  GENERIC_VALIDATE_ERROR_KEY,
  keyForStatus,
  VALIDATE_ERROR_TABLE,
} from "../lib/manage-error";
import { useCleaningFiltersStore } from "../state/use-cleaning-filters-store";
import { CancelCleaningTaskDialog } from "./cancel-cleaning-task-dialog";
import { CleaningFilters } from "./cleaning-filters";
import { CleaningPagination } from "./cleaning-pagination";
import { CleaningTaskRow } from "./cleaning-task-row";
import { CreateCleaningTaskPanel } from "./create-cleaning-task-panel";

/**
 * One entry of the announcement precedence chain (design D4): a mutation this
 * view owns, tagged with the name `announcement()` uses to pick its copy.
 *
 * The rule, exactly, is: whichever mutation `isPending` wins outright (ties
 * broken by array order — `create` first, since it is checked first below);
 * failing that, among every mutation currently `isError`, the one with the
 * **largest `submittedAt`** (TanStack Query stamps this on every `mutate()`
 * call, pending or not, so it is a reliable "most recently invoked" clock);
 * failing that, the same "largest `submittedAt`" rule among every mutation
 * currently `isSuccess`. Errors outrank successes regardless of recency —
 * only within the same category does recency decide.
 *
 * Section 5 (validate) and section 6 (cancel) extend this by adding one more
 * entry to the array `announcement()` builds and one more branch to render its
 * copy — the precedence function itself does not change.
 *
 * **Section 6's addition is the one declared exception (design D4).** Cancellation's
 * failure is painted `role="alert"` **inside** `CancelCleaningTaskDialog`, which stays
 * open on a rejection so the manager can read it there and retry or dismiss — never in
 * this region. So the `cancel` entry always carries `isError: false` here, whatever the
 * mutation's real state: it can still win the "pending" slot (so the region says
 * "cancelling…" while the dialog is open and sending) and the "success" slot (so the
 * region announces the result once the dialog has closed on success), but it can never
 * be chosen via the "error" branch, and `announcement()` has no `kind === "cancel" &&
 * via === "error"` case to render.
 */
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
    const latest = errored.reduce((a, b) => (b.submittedAt > a.submittedAt ? b : a));
    return { kind: latest.kind, via: "error" };
  }
  const succeeded = sources.filter((source) => source.isSuccess);
  if (succeeded.length > 0) {
    const latest = succeeded.reduce((a, b) => (b.submittedAt > a.submittedAt ? b : a));
    return { kind: latest.kind, via: "success" };
  }
  return null;
}

/**
 * The manager's cleaning list (`/cleaning`, PRD §6, §24). It orchestrates the three
 * queries and the filter store and owns the cross-cutting states.
 *
 * Loading, error and empty are tied to the **task** query alone (R1.2, R1.3, R1.4).
 * A catalog that fails does NOT reach `ErrorState` (design D5): the information that
 * matters — status, dates — has already arrived, and the identity degrades to R2.4's
 * indicator instead of taking the whole view down.
 *
 * There is exactly one live region, `role="status" aria-live="polite"` (design D11).
 * It is present from the first render so a screen reader is already observing it when
 * the first assignment result lands in it (section 8); N regions would be N places
 * that might have spoken.
 */
export function CleaningView() {
  const { t } = useTranslation("cleaning");
  const { t: tStates } = useTranslation("states");
  const {
    tenantId: filtersTenantId,
    propertyId,
    status,
    page,
    setPage,
    adoptTenant,
  } = useCleaningFiltersStore();
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? undefined;

  /**
   * Filters chosen in another session must not be re-sent in this one — one tenant's
   * opaque identifier travelling into another's request (`steering/security.md` rule
   * 1, frontend side). The store owns that invariant; the view only reports who is
   * looking and refuses to use filters that are not theirs.
   *
   * `staleFilters` covers the very first render, because the effect that adopts the
   * tenant runs only after it — and by then the query would already have gone out
   * carrying the previous session's filter.
   */
  const staleFilters = filtersTenantId !== tenantId;
  useEffect(() => {
    adoptTenant(tenantId);
  }, [adoptTenant, tenantId]);

  const activePropertyId = staleFilters ? undefined : propertyId;
  const activeStatus = staleFilters ? undefined : status;
  const activePage = staleFilters ? 1 : page;

  const filters = {
    ...(activePropertyId !== undefined ? { propertyId: activePropertyId } : {}),
    ...(activeStatus !== undefined ? { status: activeStatus } : {}),
  };
  const tasksQuery = useCleaningTasks(filters, activePage);
  const cleanerDirectory = useCleanerDirectory();
  const propertyDirectory = usePropertyDirectory();
  const assign = useAssignCleaningTask();
  const create = useCreateCleaningTask();
  const validate = useValidateCleaningTask();
  const cancel = useCancelCleaningTask();
  const canManage = useHasPermission("MANAGE_CLEANING_TASKS");
  const [createOpen, setCreateOpen] = useState(false);
  // `null` means no dialog is open; otherwise the id of the row that opened it
  // (design D4 — the view owns both the dialog's open state and the single shared
  // `useCancelCleaningTask()` instance).
  const [cancelTaskId, setCancelTaskId] = useState<string | null>(null);

  const cleaners = {
    index: buildDirectory(cleanerDirectory.data),
    isPending: cleanerDirectory.isPending,
  };
  const properties = {
    index: buildDirectory(propertyDirectory.data),
    isPending: propertyDirectory.isPending,
  };

  function body() {
    if (tasksQuery.isPending) {
      return <LoadingState label={tStates("loading.label")} />;
    }
    if (tasksQuery.isError) {
      return (
        <ErrorState
          title={t("list.error.title")}
          description={t("list.error.description")}
          onRetry={() => void tasksQuery.refetch()}
          retryLabel={tStates("error.retry")}
        />
      );
    }
    const tasks = tasksQuery.data.data;
    if (tasks.length === 0) {
      return (
        <EmptyState
          title={t("list.empty.title")}
          description={t("list.empty.description")}
        />
      );
    }
    return (
      <>
        <ul
          aria-label={t("list.label")}
          className="grid grid-cols-1 items-stretch gap-4 p-4 xl:grid-cols-2"
        >
          {tasks.map((task) => (
            <CleaningTaskRow
              key={task.id}
              task={task}
              properties={properties}
              cleaners={cleaners}
              assignment={{
                isPending:
                  assign.isPending && assign.variables?.taskId === task.id,
                // Any assignment in flight blocks them all: the view owns one
                // mutation, and a second `mutate` would detach the first and lose
                // its rejection, which R4.4/R4.5 require to be announced.
                isBlocked: assign.isPending,
                onConfirm: assign.mutate,
              }}
              validate={{
                isPending:
                  validate.isPending && validate.variables?.taskId === task.id,
                // Same reasoning as `assignment.isBlocked` above: the view owns one
                // validate mutation, so a second row's verdict has to wait for the
                // first to settle or its rejection would be lost.
                isBlocked: validate.isPending,
                onValidate: validate.mutate,
              }}
              cancel={{
                onOpen: () => setCancelTaskId(task.id),
                // Any cancellation in flight blocks every row's open button (fix
                // round, Finding 1, referent D4) — same reasoning as
                // `assignment.isBlocked` above: the view owns one shared
                // `useCancelCleaningTask()` instance, and opening a second row's
                // dialog while the first is submitting would remount the dialog
                // body, whose mount effect calls `mutation.reset()` on the very
                // same in-flight mutation object.
                isBlocked: cancel.isPending,
              }}
            />
          ))}
        </ul>
        <CleaningPagination
          page={tasksQuery.data.page}
          totalPages={tasksQuery.data.total_pages}
          total={tasksQuery.data.total}
          onPageChange={setPage}
        />
      </>
    );
  }

  /**
   * What the single live region says (design D4, D11, R1.4, R1.5, R5.4). Success is
   * `polite` — neither a correct assignment nor a correct creation is an urgency —
   * and only a failure is marked `alert`, inside the same region, the way
   * `features/guest-portal` does it.
   *
   * `pickAnnouncementSource` picks WHICH mutation gets to speak (create outranks
   * assign while pending, then the most recently `submittedAt` of whichever is
   * `isError`, then of whichever is `isSuccess` — see its doc comment above for the
   * exact rule section 5/6 must keep extending). This function only renders the
   * copy for whichever mutation won.
   *
   * The failure text for creation comes from `keyForStatus`/`CREATE_ERROR_TABLE`, for
   * validation from `keyForStatus`/`VALIDATE_ERROR_TABLE` (R3.5), and for assignment from
   * `assignErrorKey` — all chosen by HTTP status and never taken from `ApiError.message`
   * (design D10, R1.4, R5.1).
   */
  function announcement(): ReactNode {
    const source = pickAnnouncementSource([
      {
        kind: "create",
        isPending: create.isPending,
        isError: create.isError,
        isSuccess: create.isSuccess,
        submittedAt: create.submittedAt,
      },
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
        // Never true here (design D4's declared exception, documented on
        // `AnnouncementSource` above): a rejected cancellation is announced inside
        // `CancelCleaningTaskDialog`, not in this region.
        isError: false,
        isSuccess: cancel.isSuccess,
        submittedAt: cancel.submittedAt,
      },
    ]);
    if (source === null) {
      return null;
    }
    if (source.kind === "create") {
      if (source.via === "pending") {
        return t("create.sending");
      }
      if (source.via === "error") {
        return (
          <span role="alert">
            {t(keyForStatus(create.error, CREATE_ERROR_TABLE, GENERIC_CREATE_ERROR_KEY))}
          </span>
        );
      }
      return t("create.success");
    }
    if (source.kind === "validate") {
      if (source.via === "pending") {
        return t("validate.sending");
      }
      if (source.via === "error") {
        return (
          <span role="alert">
            {t(keyForStatus(validate.error, VALIDATE_ERROR_TABLE, GENERIC_VALIDATE_ERROR_KEY))}
          </span>
        );
      }
      // The verdict comes from the task the backend returned, not from what was sent —
      // same reasoning as assign's success copy below.
      // Non-null: `source.via === "success"` only happens when `validate` was the
      // entry picked from `succeeded` in `pickAnnouncementSource`, i.e. `validate.isSuccess`
      // was true when this array was built — TanStack Query guarantees `data` is defined
      // whenever a mutation's status is "success".
      return t(
        validate.data!.validationStatus === "FAILED"
          ? "validate.success.failed"
          : "validate.success.passed",
      );
    }
    if (source.kind === "cancel") {
      // `source.via === "error"` cannot happen — `cancel`'s `isError` is always
      // `false` in the array above, so `pickAnnouncementSource` never selects it via
      // that branch. Only "pending" and "success" reach here.
      return t(source.via === "pending" ? "cancel.sending" : "cancel.success");
    }
    // source.kind === "assign"
    if (source.via === "pending") {
      return t("assign.sending");
    }
    if (source.via === "error") {
      return <span role="alert">{t(assignErrorKey(assign.error))}</span>;
    }
    // The name comes from the task the backend returned, not from what was picked.
    // Non-null: `source.via === "success"` only happens when `assign` was the entry
    // picked from `succeeded` in `pickAnnouncementSource`, i.e. `assign.isSuccess`
    // was true when this array was built — TanStack Query guarantees `data` is
    // defined whenever a mutation's status is "success".
    const assigned = resolveIdentity(assign.data!.assignedCleanerId, cleaners);
    return t("assign.success", {
      name:
        assigned.kind === "resolved"
          ? assigned.value.name
          : t("identity.unavailable"),
    });
  }

  return (
    <div className="flex min-w-0 flex-col">
      {canManage ? (
        <div className="mx-4 mt-4">
          <CreateCleaningTaskPanel
            open={createOpen}
            onOpenChange={setCreateOpen}
            mutation={create}
          />
        </div>
      ) : null}
      <CleaningFilters />
      {/* The single live region of design D11. */}
      <div
        role="status"
        aria-live="polite"
        className="px-4 py-2 text-body-base text-muted-foreground empty:hidden"
      >
        {announcement()}
      </div>
      {body()}
      {/*
        One dialog for the whole view (design D4): `cancelTaskId` says which row
        opened it, `null` means closed. `mutation` is the same shared instance
        `announcement()` reads above, never a second one instantiated here.
      */}
      <CancelCleaningTaskDialog
        open={cancelTaskId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setCancelTaskId(null);
          }
        }}
        taskId={cancelTaskId ?? ""}
        mutation={cancel}
      />
    </div>
  );
}
