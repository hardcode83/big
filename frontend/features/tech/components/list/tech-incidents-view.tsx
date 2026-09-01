"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import {
  mapIncidentsError,
  useIncidentContexts,
  useIncidentsPages,
  type IncidentFilters,
} from "@/features/incidents";

import { TechIncidentRow } from "./tech-incident-row";
import { TechStatusChips } from "./tech-status-chips";

const PER_PAGE = 20;

/**
 * `/tech` — the technician's own incidents (proposal R1).
 *
 * The list is requested with **no parameter identifying the technician**: the
 * backend narrows the rows from the token (`IncidentActor.restrict_to_technician_id`)
 * and there is no query parameter for it (R1.1).
 *
 * Both reads come from the incidents data layer through the barrel (design D1):
 * `useIncidentsPages` accumulates the pages D5 asks for, and
 * `useIncidentContexts` mounts one entry per row under
 * `incidentsKeys.context(tenantId, row.id)` — **the same** key the detail uses,
 * which is what makes opening a row skip a second request for its context
 * (R1.3, D4). A context that fails degrades that row to `—` without taking the
 * list down: R1.6 governs the failure of the *list* request, not of an
 * accessory projection.
 */
export function TechIncidentsView() {
  const { t } = useTranslation(["tech", "incidents"]);
  const [filters, setFilters] = useState<IncidentFilters>({});
  const [pageCount, setPageCount] = useState(1);

  const list = useIncidentsPages(filters, pageCount, PER_PAGE);
  const state = mapIncidentsError(list);
  const contexts = useIncidentContexts(list.rows.map((row) => row.id));

  const onFiltersChange = (next: IncidentFilters) => {
    setFilters(next);
    setPageCount(1);
  };

  const heading = (
    <>
      <h1 className="text-xl font-semibold text-foreground">
        {t("tech:list.title")}
      </h1>
      <TechStatusChips value={filters} onChange={onFiltersChange} />
    </>
  );

  if (state.kind === "loading") {
    return (
      <section className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
        {heading}
        <LoadingState label={t("tech:list.loading")} />
      </section>
    );
  }

  if (state.kind !== "ok") {
    return (
      <section className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
        {heading}
        <ErrorState
          title={t("tech:list.error.title")}
          description={t("tech:list.error.description")}
          retryLabel={t("tech:list.error.retry")}
          onRetry={list.refetch}
        />
      </section>
    );
  }

  return (
    <section className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      {heading}
      {/*
        R1.4 scopes this notice to the unfiltered list. With a chip active the
        statement is simply false — a list filtered to `IN_PROGRESS` carries no
        closed incident — so it is rendered only where the requirement puts it.
      */}
      {filters.status === undefined ? (
        <p className="text-sm text-muted-foreground">
          {t("tech:list.includesClosed")}
        </p>
      ) : null}

      {list.rows.length === 0 ? (
        <EmptyState
          title={t("tech:list.empty.title")}
          description={t("tech:list.empty.description")}
        />
      ) : (
        <>
          <ul className="flex flex-col gap-3">
            {list.rows.map((row, index) => {
              const context = contexts[index];
              return (
                <TechIncidentRow
                  key={row.id}
                  incident={row}
                  propertyName={context?.propertyName ?? null}
                  propertyInternalCode={context?.propertyInternalCode ?? null}
                />
              );
            })}
          </ul>
          {/*
            A page after the first failed. The rows already fetched stay on
            screen — R1.6's whole-screen `ErrorState` is for the list being
            unavailable, which is not this — but the failure is reported and
            «load more» is withdrawn, because paging past a hole would strand
            the missing incidents silently.
          */}
          {list.hasPageError ? (
            <ErrorState
              title={t("tech:list.moreError.title")}
              description={t("tech:list.moreError.description")}
              retryLabel={t("tech:list.moreError.retry")}
              onRetry={list.retryPage}
            />
          ) : null}

          {list.hasMore ? (
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={list.isFetchingMore}
              onClick={() => setPageCount((count) => count + 1)}
            >
              {t("tech:list.loadMore")}
            </Button>
          ) : null}
        </>
      )}
    </section>
  );
}
