"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useAuth } from "@/lib/auth";

import { useAssignCleaningTask } from "../hooks/use-assign-cleaning-task";
import {
  useCleanerDirectory,
  useCleaningTasks,
  usePropertyDirectory,
} from "../hooks/use-cleaning-data";
import { assignErrorKey } from "../lib/assign-error";
import { buildDirectory, resolveIdentity } from "../lib/directory";
import { useCleaningFiltersStore } from "../state/use-cleaning-filters-store";
import { CleaningFilters } from "./cleaning-filters";
import { CleaningPagination } from "./cleaning-pagination";
import { CleaningTaskRow } from "./cleaning-task-row";

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
          className="grid grid-cols-1 gap-4 p-4 xl:grid-cols-2"
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
   * What the single live region says (design D11, R5.4). Success is `polite` — a
   * correct assignment is not an urgency — and only the failure is marked `alert`,
   * inside the same region, the way `features/guest-portal` does it.
   *
   * The failure text comes from `assignErrorKey`, so it is chosen by HTTP status and
   * never taken from `ApiError.message` (design D10, R5.1).
   */
  function announcement(): ReactNode {
    if (assign.isPending) {
      return t("assign.sending");
    }
    if (assign.isError) {
      return <span role="alert">{t(assignErrorKey(assign.error))}</span>;
    }
    if (assign.isSuccess) {
      // The name comes from the task the backend returned, not from what was picked.
      const assigned = resolveIdentity(assign.data.assignedCleanerId, cleaners);
      return t("assign.success", {
        name:
          assigned.kind === "resolved"
            ? assigned.value.name
            : t("identity.unavailable"),
      });
    }
    return null;
  }

  return (
    <div className="flex min-w-0 flex-col">
      <CleaningFilters />
      {/* The single live region of design D11. */}
      <div role="status" aria-live="polite" className="px-4 empty:hidden">
        {announcement()}
      </div>
      {body()}
    </div>
  );
}
