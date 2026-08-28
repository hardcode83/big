"use client";

import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";
import {
  getIncidentsDataSource,
  incidentsKeys,
  mapIncidentsError,
  useIncidents,
  type IncidentContextDto,
  type IncidentFilters,
  type IncidentSummaryDto,
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
 * The property of each row comes from a `useQueries` over the accumulated rows,
 * one entry per row under `incidentsKeys.context(tenantId, row.id)` — **the same
 * key** the detail uses, which is what makes opening a row skip a second request
 * for its context (R1.3, design D4). A context that fails degrades that row to
 * `—` without taking the list down: R1.6 governs the failure of the *list*
 * request, not of an accessory projection.
 */
export function TechIncidentsView() {
  const { t } = useTranslation(["tech", "incidents"]);
  const { user } = useAuth();
  const tenantId = user?.tenant_id;
  const [filters, setFilters] = useState<IncidentFilters>({});
  const [pageCount, setPageCount] = useState(1);

  const pages = useQueries({
    queries: Array.from({ length: pageCount }, (_, index) => {
      const pageFilters: IncidentFilters = {
        ...(filters.status !== undefined ? { status: filters.status } : {}),
        page: index + 1,
        perPage: PER_PAGE,
      };
      return {
        queryKey: incidentsKeys.list(tenantId ?? "", pageFilters),
        queryFn: () =>
          getIncidentsDataSource().listIncidents(tenantId ?? "", pageFilters),
        retry: retryPolicy,
        enabled: Boolean(tenantId),
      };
    }),
  });

  const firstPage = pages[0];
  const state = mapIncidentsError({
    isPending: firstPage?.isPending ?? true,
    isError: firstPage?.isError ?? false,
    error: firstPage?.error ?? null,
    data: firstPage?.data,
  });

  const rows: IncidentSummaryDto[] = pages.flatMap(
    (page) => page.data?.items ?? [],
  );
  const total = firstPage?.data?.total ?? 0;

  const contexts = useQueries({
    queries: rows.map((row) => ({
      queryKey: incidentsKeys.context(tenantId ?? "", row.id),
      queryFn: () =>
        getIncidentsDataSource().getIncidentContext(tenantId ?? "", row.id),
      retry: retryPolicy,
      enabled: Boolean(tenantId),
    })),
  });

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
          onRetry={() => {
            void firstPage?.refetch();
          }}
        />
      </section>
    );
  }

  const hasMore = rows.length < total;

  return (
    <section className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      {heading}
      <p className="text-sm text-muted-foreground">
        {t("tech:list.includesClosed")}
      </p>

      {rows.length === 0 ? (
        <EmptyState
          title={t("tech:list.empty.title")}
          description={t("tech:list.empty.description")}
        />
      ) : (
        <>
          <ul className="flex flex-col gap-3">
            {rows.map((row, index) => {
              const context = contexts[index]?.data as
                | IncidentContextDto
                | undefined;
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
          {hasMore ? (
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
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
