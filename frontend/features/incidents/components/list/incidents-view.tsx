"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";

import type { IncidentFilters } from "../../data";
import { mapIncidentsError } from "../../lib/error-mapping";
import { severityColorGroup } from "../../lib/severity-tone";
import { useIncidents } from "../../hooks/use-incidents";
import { IncidentsFilters } from "./incidents-filters";

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/**
 * The list view for `/incidents` (proposal R2, design D5). Six columns,
 * no `property` column (D5: the endpoint returns `propertyId` and we don't
 * resolve it to a name). Pagination uses `lastPage` derived in the client
 * (R2.5): `max(1, ceil(total / perPage))`.
 */
export function IncidentsView() {
  const { t } = useTranslation(["incidents", "states", "navigation"]);
  const [filters, setFilters] = useState<IncidentFilters>({});
  const query = useIncidents(filters);
  const state = mapIncidentsError(query);

  if (state.kind === "loading") {
    return <p className="p-4 text-body-base text-muted-foreground">{t("states:loading.label", { ns: "states" })}</p>;
  }
  if (state.kind === "forbidden") {
    return <p className="p-4 text-body-base text-muted-foreground">{t("incidents:fields.forbidden")}</p>;
  }
  if (state.kind === "validation") {
    return <p className="p-4 text-body-base text-muted-foreground">{t("incidents:fields.validation")}</p>;
  }
  if (state.kind === "not-found") {
    // A 404 on the list is treated as a generic error per design (the list
    // endpoint shouldn't produce 404). Reaching here means the BE gave 404;
    // the dashboard precedent is to fall through to the generic error UI.
    return (
      <div className="flex flex-col gap-2 p-4">
        <p className="text-body-lg font-semibold text-foreground">{t("states:error.title", { ns: "states" })}</p>
        <p className="text-body-base text-muted-foreground">{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
          className="tap-target self-start rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground"
          onClick={() => {
            void query.refetch();
          }}
        >
          {t("states:error.retry", { ns: "states" })}
        </button>
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="flex flex-col gap-2 p-4">
        <p className="text-body-lg font-semibold text-foreground">{t("states:error.title", { ns: "states" })}</p>
        <p className="text-body-base text-muted-foreground">{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
          className="tap-target self-start rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground"
          onClick={() => {
            void query.refetch();
          }}
        >
          {t("states:error.retry", { ns: "states" })}
        </button>
      </div>
    );
  }
  // state.kind === "ok"
  const lastPage = Math.max(1, Math.ceil(state.data.total / state.data.perPage));
  const isFirstPage = state.data.page <= 1;
  const isLastPage = state.data.page >= lastPage;
  const onPrev = () => {
    if (isFirstPage) return;
    setFilters((prev) => ({ ...prev, page: (state.data.page ?? 1) - 1 }));
  };
  const onNext = () => {
    if (isLastPage) return;
    setFilters((prev) => ({ ...prev, page: (state.data.page ?? 1) + 1 }));
  };

  return (
    <section aria-labelledby="incidents-heading" className="flex flex-col gap-4 p-4">
      <h1 id="incidents-heading" className="text-xl font-semibold text-foreground">
        {t("navigation:routes.incidents.title", { ns: "navigation" })}
      </h1>
      <IncidentsFilters value={filters} onChange={setFilters} />
      {state.data.items.length === 0 ? (
        <>
          <p className="text-body-lg font-semibold text-foreground">{t("states:empty.title", { ns: "states" })}</p>
          <p className="text-body-base text-muted-foreground">{t("states:empty.description", { ns: "states" })}</p>
        </>
      ) : (
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("incidents:fields.severity")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("incidents:fields.status")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("incidents:fields.title")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("incidents:fields.category")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("incidents:fields.source")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("incidents:fields.createdAt")}
                </th>
              </tr>
            </thead>
            <tbody className="font-mono text-data-mono">
              {state.data.items.map((row) => (
                <tr key={row.id} className="border-b border-border last:border-b-0 hover:bg-accent/50 transition-colors">
                  <td className="px-4 py-3 font-sans text-body-base">
                    <span
                      className={TONE_BADGE_CLASS[severityColorGroup(row.severity)]}
                    >
                      {t(`incidents:severity.${row.severity}`)}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-sans text-body-base">{t(`incidents:status.${row.status}`)}</td>
                  <td className="px-4 py-3 font-sans text-body-base">
                    <Link
                      href={`/incidents/${row.id}`}
                      title={row.title}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {truncate(row.title, 60)}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-sans text-body-base">{t(`incidents:category.${row.category}`)}</td>
                  <td className="px-4 py-3 font-sans text-body-base">{t(`incidents:source.${row.source}`)}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {row.createdAt.slice(0, 16).replace("T", " ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
      <nav aria-label={t("incidents:fields.status")} className="flex items-center gap-2">
        <button
          type="button"
          className="tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
          onClick={onPrev}
          disabled={isFirstPage}
          aria-label={t("incidents:fields.prevPage")}
        >
          {t("incidents:fields.prevPage")}
        </button>
        <button
          type="button"
          className="tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
          onClick={onNext}
          disabled={isLastPage}
          aria-label={t("incidents:fields.nextPage")}
        >
          {t("incidents:fields.nextPage")}
        </button>
      </nav>
    </section>
  );
}