"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PropertyStateBadge } from "@/components/property-state-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";

import type { PropertyFilters, PropertySummaryDto } from "../../data";
import { useProperties } from "../../hooks/use-properties";
import { mapPropertiesError } from "../../lib/error-mapping";
import { PropertiesFilters } from "./properties-filters";

/** The six columns, closed list, in this order (R1.2 / design D11). */
const COLUMNS = [
  "name",
  "internalCode",
  "city",
  "capacity",
  "operationalState",
  "status",
] as const;

/**
 * The capacity cell. Three separately-pluralized fragments composed by a
 * template that owns the separator, so nothing is spelled in code (R6.4) and
 * `1` reads correctly: i18next pluralizes on a single `count`, so one string
 * with three counts would produce "1 baños".
 */
function useCapacityLabel() {
  const { t } = useTranslation("properties");
  return (property: PropertySummaryDto) =>
    t("capacity.summary", {
      guests: t("capacity.guests", { count: property.maxGuests }),
      bedrooms: t("capacity.bedrooms", { count: property.bedrooms }),
      bathrooms: t("capacity.bathrooms", { count: property.bathrooms }),
    });
}

/** The row's name cell: the link to the detail that already exists (R1.5). */
function NameLink({ property }: { property: PropertySummaryDto }) {
  const { t } = useTranslation("properties");
  return (
    <Link
      href={`/properties/${property.id}`}
      aria-label={t("row.openDetail", { name: property.name })}
      className="font-medium text-primary underline-offset-4 hover:underline"
    >
      {property.name}
    </Link>
  );
}

/**
 * One table row, for `sm` and up. Declared at module level on purpose: a
 * component defined inside its parent gets a new identity on every render, so
 * React remounts every row instead of reconciling by `key`. Both precedents in
 * the tree keep these out (`ReservationRow` in `reservations-view.tsx`, `Field`
 * in `property-card.tsx`).
 */
function PropertyRow({ property }: { property: PropertySummaryDto }) {
  const { t } = useTranslation("properties");
  const { t: tDashboard } = useTranslation("dashboard");
  const capacityLabel = useCapacityLabel();

  return (
    <tr className="border-b last:border-0">
      <td className="px-3 py-2">
        <NameLink property={property} />
      </td>
      <td className="px-3 py-2">{property.internalCode}</td>
      <td className="px-3 py-2">{property.city ?? t("cityEmpty")}</td>
      <td className="px-3 py-2">{capacityLabel(property)}</td>
      <td className="px-3 py-2">
        <PropertyStateBadge
          state={property.currentOperationalState}
          label={tDashboard(`state.${property.currentOperationalState}`)}
        />
      </td>
      <td className="px-3 py-2">
        <Badge variant="outline">{t(`status.${property.status}`)}</Badge>
      </td>
    </tr>
  );
}

/**
 * One property as a stacked card, for viewports below `sm`.
 *
 * This is the mobile-first half (`steering/frontend.md`: «diseño responsive
 * mobile-first — la propietaria opera desde el móvil»). A six-column table at
 * `min-w-[40rem]` with horizontal scroll is the inverse: it forces the owner to
 * pan sideways to read `status`, which is the one field only this screen shows.
 * So below `sm` each property is a card of label/value pairs — the same shape
 * `Field` uses in `property-card.tsx` — and the table appears from `sm` up.
 */
function PropertyCardRow({ property }: { property: PropertySummaryDto }) {
  const { t } = useTranslation("properties");
  const { t: tDashboard } = useTranslation("dashboard");
  const capacityLabel = useCapacityLabel();

  const fields: [string, React.ReactNode][] = [
    [t("columns.internalCode"), property.internalCode],
    [t("columns.city"), property.city ?? t("cityEmpty")],
    [t("columns.capacity"), capacityLabel(property)],
    [
      t("columns.operationalState"),
      <PropertyStateBadge
        key="state"
        state={property.currentOperationalState}
        label={tDashboard(`state.${property.currentOperationalState}`)}
      />,
    ],
    [
      t("columns.status"),
      <Badge key="status" variant="outline">
        {t(`status.${property.status}`)}
      </Badge>,
    ],
  ];

  return (
    <article className="flex flex-col gap-2 rounded-lg border bg-surface p-3 shadow-sm">
      <h3 className="text-base font-semibold">
        <NameLink property={property} />
      </h3>
      <dl className="flex flex-col gap-1 text-sm">
        {fields.map(([label, value]) => (
          <div
            key={label}
            className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] items-baseline gap-x-3"
          >
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 break-words text-right font-medium">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

/**
 * Client view for `/properties` (proposal R1–R4, R6).
 *
 * This is the portfolio index: "what do I have and how is it configured?", as
 * opposed to `/dashboard`'s "what needs my attention now?" (design D1). It is
 * also the only screen where a property's `status` is visible at all, and the
 * only place a bare property UUID printed by `/reservations` or `/incidents` can
 * be resolved to a name.
 *
 * Six columns, closed list (R1.2 / D11). Everything else the payload carries —
 * full address, country, timezone, default times, WiFi, PMS link, timestamps —
 * is fiche data and is deliberately NOT rendered (R1.6), which also keeps the
 * PMS link off the screen.
 *
 * The three free-text sinks are absent structurally: the list endpoint does not
 * return them (exception 6 of rule 11), and this view never fetches the detail
 * per row to "complete" a fiche (R5.1, R5.2).
 */
export function PropertiesView() {
  const { t } = useTranslation("properties");
  const { t: tStates } = useTranslation("states");
  const [filters, setFilters] = useState<PropertyFilters>({ page: 1 });
  const query = useProperties(filters);
  const state = mapPropertiesError(query);

  function body() {
    if (state.kind === "loading") {
      return <LoadingState label={tStates("loading.label")} />;
    }
    if (state.kind === "forbidden") {
      return (
        <EmptyState
          title={t("forbidden.title")}
          description={t("forbidden.description")}
        />
      );
    }
    if (state.kind === "validation") {
      return (
        <EmptyState
          title={t("validation.title")}
          description={t("validation.description")}
        />
      );
    }
    // `not-found` is unreachable for this feature — the mapper never produces it
    // (R3.5) — but the branch keeps the switch exhaustive rather than relying on
    // a default that would silently swallow a future variant.
    if (state.kind === "error" || state.kind === "not-found") {
      return (
        <ErrorState
          title={t("error.title")}
          description={t("error.description")}
          onRetry={() => void query.refetch()}
          retryLabel={tStates("error.retry")}
        />
      );
    }

    const pageData = state.data;
    if (pageData.data.length === 0) {
      return (
        <EmptyState
          title={t("empty.title")}
          description={t("empty.description")}
        />
      );
    }

    return (
      <>
        {/* Below `sm`: stacked cards, no horizontal scrolling. */}
        <div className="flex flex-col gap-3 sm:hidden">
          {pageData.data.map((property) => (
            <PropertyCardRow key={property.id} property={property} />
          ))}
        </div>

        {/* From `sm` up: the six-column table. */}
        <div className="hidden sm:block">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                {COLUMNS.map((column) => (
                  <th key={column} scope="col" className="px-3 py-2 font-medium">
                    {t(`columns.${column}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageData.data.map((property) => (
                <PropertyRow key={property.id} property={property} />
              ))}
            </tbody>
          </table>
        </div>

        {/*
          R1.3 says «WHEN la respuesta trae `total_pages` mayor que 1, THE SYSTEM
          SHALL ofrecer navegación» — so with a single page there is nothing to
          offer. Rendering a bar whose two arrows are permanently disabled is
          dead furniture, and today (no per-page control in the UI, two seeded
          properties) that is what the operator would always see. Raised by the
          QA panel on sections 4–6.
        */}
        {pageData.totalPages > 1 ? (
        <nav
          className="mt-4 flex items-center justify-between gap-3"
          aria-label={t("pagination.label")}
        >
          <button
            type="button"
            className="tap-target rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
            disabled={pageData.page <= 1}
            onClick={() =>
              setFilters({ ...filters, page: Math.max(1, pageData.page - 1) })
            }
          >
            {t("pagination.prev")}
          </button>
          <span className="text-sm text-muted-foreground">
            {t("pagination.position", {
              page: pageData.page,
              totalPages: pageData.totalPages,
            })}
          </span>
          <button
            type="button"
            className="tap-target rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
            disabled={pageData.page >= pageData.totalPages}
            onClick={() => setFilters({ ...filters, page: pageData.page + 1 })}
          >
            {t("pagination.next")}
          </button>
        </nav>
        ) : null}
      </>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <PropertiesFilters value={filters} onChange={setFilters} />
      {body()}
    </div>
  );
}
