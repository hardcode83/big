"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import {
  useCleanerTaskContexts,
  useCleanerTaskPages,
} from "../../hooks/use-cleaner-tasks";
import type { CleaningFilters } from "../../data";
import { mapCleanerError } from "../../lib/error-mapping";
import { CleanerTaskListRow } from "./cleaner-task-list-row";
import { CleanerTaskPagination } from "./cleaner-task-pagination";
import { CleanerTaskStatusChips } from "./cleaner-task-status-chips";

/**
 * The cleaner's task list at `/cleaner` (R1.1, design D4, D5, D15).
 *
 * Orchestrates the page query and the per-row context queries. Renders the
 * chips above the list and the paginator below. Loading renders
 * `LoadingState` (`role="status"`, `aria-busy`); empty renders `EmptyState`;
 * error renders `ErrorState` without retry on `4xx` (R1.7).
 *
 * `mx-auto w-full max-w-md p-4` keeps it mobile-first at 360 px (R8.3): no
 * horizontal scroll. The cards stack as a single column.
 */
export function CleanerTaskListView() {
  const { t } = useTranslation(["cleaner", "states"]);
  const [filters, setFilters] = useState<CleaningFilters>({});
  const [page, setPage] = useState(1);
  const perPage = 20;

  const pages = useCleanerTaskPages(filters, page, perPage);
  const contexts = useCleanerTaskContexts(pages.rows.map((row) => row.id));

  function handleFiltersChange(next: CleaningFilters) {
    setFilters(next);
    // Changing the filter returns to page 1 (docs/cleaning.md §Filtrar y
    // paginar): otherwise a narrower filter can strand the view on a page
    // number the new result set no longer has.
    setPage(1);
  }

  // Map the list-level error once — used by the whole-screen branch.
  const errorMap =
    pages.isError && pages.error
      ? mapCleanerError(pages.error, "task")
      : null;

  function body() {
    if (pages.isPending) {
      return <LoadingState label={t("cleaner:list.loading")} />;
    }
    if (errorMap) {
      // No retry on 4xx — those are addressed by the back-to-tasks affordance
      // or by selecting another status filter (R1.7). For 5xx, the retry is on
      // the shared `ErrorState`.
      return (
        <ErrorState
          title={t(`cleaner:${errorMap.messageKey}`)}
          description={t("cleaner:list.error.description")}
          onRetry={
            errorMap.state === "not-found"
              ? undefined
              : () => pages.refetch()
          }
          retryLabel={t("states:error.retry")}
        />
      );
    }
    if (pages.rows.length === 0) {
      return (
        <EmptyState
          title={t("cleaner:list.empty.title")}
          description={t("cleaner:list.empty.description")}
        />
      );
    }
    return (
      <>
        <ul
          aria-label={t("cleaner:list.label")}
          className="grid grid-cols-1 gap-4"
        >
          {pages.rows.map((row, index) => (
            <CleanerTaskListRow
              key={row.id}
              task={row}
              context={contexts[index] ?? null}
            />
          ))}
        </ul>
        <CleanerTaskPagination
          page={pages.page}
          totalPages={pages.totalPages}
          total={pages.total}
          onPageChange={setPage}
        />
      </>
    );
  }

  return (
    <div className="mx-auto w-full max-w-md p-4">
      <CleanerTaskStatusChips value={filters} onChange={handleFiltersChange} />
      {body()}
    </div>
  );
}