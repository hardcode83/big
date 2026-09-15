"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { OwnerStatementFilters, OwnerStatementStatus } from "../data";
import { useStatementPropertyDirectory, useStatementsList } from "../hooks/use-statements-data";
import { readErrorKey } from "../lib/statements-error";
import { StatementRow } from "./statement-row";
import { StatementsFilters } from "./statements-filters";
import { StatementsPagination } from "./statements-pagination";

/**
 * Assembles the statements surface (R1, R2, R5, task 3.4): queries, filters,
 * rows and pagination, with explicit loading/error/empty/success states.
 *
 * TanStack Query (`useStatementsList`, `useStatementPropertyDirectory`) is the
 * only source of remote state here (design D5) — `filters` and `page` are
 * owned by the parent (`StatementsView`) as plain local state and simply
 * flow down as props; this component never copies them into a store.
 *
 * **A `403`/generic failure never falls through to the empty state** (R1.2,
 * R2.4): `query.isError` is checked before `total === 0`, and both render
 * `ErrorState`/`EmptyState` instead of the list, so no row — and therefore no
 * financial figure — ever paints while the session is unauthorized or the
 * request otherwise failed. The property directory's own failure is isolated
 * (`useStatementPropertyDirectory`'s contract): it degrades row identity to
 * "unavailable" rather than turning the whole list into an error.
 */
export interface StatementsListProps {
  filters: OwnerStatementFilters;
  page: number;
  onPropertyIdChange: (value?: string) => void;
  onPeriodStartFromChange: (value?: string) => void;
  onPeriodStartToChange: (value?: string) => void;
  onStatusChange: (value?: OwnerStatementStatus) => void;
  onPageChange: (page: number) => void;
  /**
   * Bridge to the detail view (task 6.3). The parent (`StatementsView`)
   * forwards this callback from `StatementsPage`, which decides what to do
   * with the selected id (in our case, swap the page content for the
   * detail). Optional so direct/internal callers can still mount the list
   * without wiring a selection handler.
   */
  onSelectStatement?: (statementId: string) => void;
}

export function StatementsList({
  filters,
  page,
  onPropertyIdChange,
  onPeriodStartFromChange,
  onPeriodStartToChange,
  onStatusChange,
  onPageChange,
  onSelectStatement,
}: StatementsListProps) {
  const { t } = useTranslation("statements");
  const { t: tStates } = useTranslation("states");

  const query = useStatementsList(filters, page);
  const propertyDirectory = useStatementPropertyDirectory();
  const propertyOptions = (propertyDirectory.data?.data ?? []).map((property) => ({
    id: property.id,
    name: property.name,
  }));

  function body() {
    // R5.1 / task 3.4 — explicit busy treatment covers BOTH the initial
    // pending fetch AND background refetches triggered by filter/page changes.
    // Without this, `isPending` flips false the moment cached data exists,
    // and subsequent refetches would keep the previous render on screen with
    // no loading signal — the list would stay interactive while showing stale
    // data.
    if (query.isPending || query.isFetching) {
      return <LoadingState label={tStates("loading.label")} />;
    }
    if (query.isError) {
      return (
        <ErrorState
          title={tStates("error.title")}
          description={t(readErrorKey(query.error))}
          onRetry={() => void query.refetch()}
          retryLabel={tStates("error.retry")}
        />
      );
    }

    const { items, total, page: currentPage, perPage } = query.data;
    // total=0 IS the empty listing (R2.1) — never rendered as an error, and
    // distinguishable from it because we only reach here once isError is false.
    if (total === 0) {
      return (
        <EmptyState title={t("list.empty.title")} description={t("list.empty.description")} />
      );
    }

    return (
      <>
        <ul aria-label={t("list.label")} className="flex flex-col gap-3 p-4">
          {items.map((statement) => (
            <StatementRow
              key={statement.id}
              statement={statement}
              properties={propertyDirectory}
              onSelect={onSelectStatement}
            />
          ))}
        </ul>
        <StatementsPagination
          page={currentPage}
          total={total}
          perPage={perPage}
          onPageChange={onPageChange}
        />
      </>
    );
  }

  return (
    <div className="flex min-w-0 flex-col" data-testid="statements-list">
      <div className="m-4 rounded-lg border border-border bg-surface/60 p-3 backdrop-blur-md">
        <StatementsFilters
          properties={propertyOptions}
          propertyId={filters.propertyId}
          onPropertyIdChange={onPropertyIdChange}
          periodStartFrom={filters.periodStartFrom}
          onPeriodStartFromChange={onPeriodStartFromChange}
          periodStartTo={filters.periodStartTo}
          onPeriodStartToChange={onPeriodStartToChange}
          status={filters.status}
          onStatusChange={onStatusChange}
        />
      </div>
      {body()}
    </div>
  );
}
