"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { IncidentFilters } from "../../data";
import { mapIncidentsError } from "../../lib/error-mapping";
import { useIncidents } from "../../hooks/use-incidents";
import { IncidentsFilters } from "./incidents-filters";

const SEVERITY_COLOR: Record<string, string> = {
  LOW: "bg-gray-100 text-gray-700",
  MEDIUM: "bg-blue-100 text-blue-700",
  HIGH: "bg-amber-100 text-amber-800",
  CRITICAL: "bg-red-100 text-red-700",
};

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
                    className={
                      SEVERITY_COLOR[row.severity] ?? "bg-gray-100 text-gray-700"
                    }
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