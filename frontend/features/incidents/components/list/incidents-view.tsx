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
    return <p>{t("states:loading.label", { ns: "states" })}</p>;
  }
  if (state.kind === "forbidden") {
    return <p>{t("incidents:fields.forbidden")}</p>;
  }
  if (state.kind === "validation") {
    return <p>{t("incidents:fields.validation")}</p>;
  }
  if (state.kind === "not-found") {
    // A 404 on the list is treated as a generic error per design (the list
    // endpoint shouldn't produce 404). Reaching here means the BE gave 404;
    // the dashboard precedent is to fall through to the generic error UI.
    return (
      <div>
        <p>{t("states:error.title", { ns: "states" })}</p>
        <p>{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
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
      <div>
        <p>{t("states:error.title", { ns: "states" })}</p>
        <p>{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
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
    <section aria-labelledby="incidents-heading">
      <h1 id="incidents-heading">
        {t("navigation:routes.incidents.title", { ns: "navigation" })}
      </h1>
      <IncidentsFilters value={filters} onChange={setFilters} />
      {state.data.items.length === 0 ? (
        <>
          <p>{t("states:empty.title", { ns: "states" })}</p>
          <p>{t("states:empty.description", { ns: "states" })}</p>
        </>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">{t("incidents:fields.severity")}</th>
              <th scope="col">{t("incidents:fields.status")}</th>
              <th scope="col">{t("incidents:fields.title")}</th>
              <th scope="col">{t("incidents:fields.category")}</th>
              <th scope="col">{t("incidents:fields.source")}</th>
              <th scope="col">{t("incidents:fields.createdAt")}</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((row) => (
              <tr key={row.id}>
                <td>
                  <span
                    className={TONE_BADGE_CLASS[severityColorGroup(row.severity)]}
                  >
                    {t(`incidents:severity.${row.severity}`)}
                  </span>
                </td>
                <td>{t(`incidents:status.${row.status}`)}</td>
                <td>
                  <Link href={`/incidents/${row.id}`} title={row.title}>
                    {truncate(row.title, 60)}
                  </Link>
                </td>
                <td>{t(`incidents:category.${row.category}`)}</td>
                <td>{t(`incidents:source.${row.source}`)}</td>
                <td>
                  {row.createdAt.slice(0, 16).replace("T", " ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <nav aria-label={t("incidents:fields.status")}>
        <button
          type="button"
          onClick={onPrev}
          disabled={isFirstPage}
          aria-label={t("incidents:fields.prevPage")}
        >
          {t("incidents:fields.prevPage")}
        </button>
        <button
          type="button"
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