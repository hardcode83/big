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

/**
 * Client view for `/properties` (proposal R1–R4, R6).
 *
 * This is the portfolio index: "what do I have and how is it configured?", as
 * opposed to `/dashboard`'s "what needs my attention now?" (design D1). It is
 * also the only screen where a property's `status` is visible at all, and the
 * only place a bare property UUID printed by `/reservations` or `/incidents`
 * can be resolved to a name.
 *
 * Six columns, closed list, in this order (R1.2 / design D11): name (with the
 * row link), internal code, city, capacity, operational state, status.
 * Everything else the payload carries — full address, country, timezone,
 * default times, WiFi, PMS link, timestamps — is fiche data and is deliberately
 * NOT rendered (R1.6), which also keeps the PMS link off the screen.
 *
 * The three free-text sinks are absent structurally: the list endpoint does not
 * return them (exception 6 of rule 11), and this view never fetches the detail
 * per row to "complete" a fiche (R5.1, R5.2).
 */
export function PropertiesView() {
  const { t } = useTranslation("properties");
  const { t: tDashboard } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const [filters, setFilters] = useState<PropertyFilters>({ page: 1 });
  const query = useProperties(filters);
  const state = mapPropertiesError(query);

  const columns = [
    "name",
    "internalCode",
    "city",
    "capacity",
    "operationalState",
    "status",
  ] as const;

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

    const page = state.data;
    if (page.data.length === 0) {
      return (
        <EmptyState
          title={t("empty.title")}
          description={t("empty.description")}
        />
      );
    }

    return (
      <>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                {columns.map((column) => (
                  <th key={column} scope="col" className="px-3 py-2 font-medium">
                    {t(`columns.${column}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.data.map((property) => (
                <Row key={property.id} property={property} />
              ))}
            </tbody>
          </table>
        </div>

        <nav
          className="mt-4 flex items-center justify-between gap-3"
          aria-label={t("pagination.position", {
            page: page.page,
            totalPages: page.totalPages,
          })}
        >
          <button
            type="button"
            className="tap-target rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
            disabled={page.page <= 1}
            onClick={() =>
              setFilters({ ...filters, page: Math.max(1, page.page - 1) })
            }
          >
            {t("pagination.prev")}
          </button>
          <span className="text-sm text-muted-foreground">
            {t("pagination.position", {
              page: page.page,
              totalPages: page.totalPages,
            })}
          </span>
          <button
            type="button"
            className="tap-target rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
            disabled={page.page >= page.totalPages}
            onClick={() => setFilters({ ...filters, page: page.page + 1 })}
          >
            {t("pagination.next")}
          </button>
        </nav>
      </>
    );
  }

  /** One table row. Every rendered value is text interpolation, never HTML (R5.4). */
  function Row({ property }: { property: PropertySummaryDto }) {
    return (
      <tr className="border-b last:border-0">
        <td className="px-3 py-2">
          <Link
            href={`/properties/${property.id}`}
            aria-label={t("row.openDetail", { name: property.name })}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            {property.name}
          </Link>
        </td>
        <td className="px-3 py-2">{property.internalCode}</td>
        <td className="px-3 py-2">{property.city ?? t("cityEmpty")}</td>
        <td className="px-3 py-2">
          {t("capacity.summary", {
            guests: property.maxGuests,
            bedrooms: property.bedrooms,
            bathrooms: property.bathrooms,
          })}
        </td>
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

  return (
    <div className="flex flex-col gap-4 p-4">
      <PropertiesFilters
        value={filters}
        onChange={(next) => setFilters(next)}
      />
      {body()}
    </div>
  );
}
