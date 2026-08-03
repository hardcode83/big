"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import { useDashboardCards } from "../hooks/use-dashboard-data";
import { PropertyCard } from "./property-card";

/**
 * Client view for `/dashboard` (PRD §9.1). It consumes `useDashboardCards` and
 * renders the cross-cutting loading/error/empty states from the shell, then a
 * responsive grid of `PropertyCard`. It never exposes raw error detail — the
 * error copy is localized and retry re-runs the query.
 */
export function DashboardView() {
  const { t } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const query = useDashboardCards();

  if (query.isPending) {
    return <LoadingState label={tStates("loading.label")} />;
  }

  if (query.isError) {
    return (
      <ErrorState
        title={t("cards.error.title")}
        description={t("cards.error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }

  const cards = query.data.data;
  if (cards.length === 0) {
    return (
      <EmptyState
        title={t("cards.empty.title")}
        description={t("cards.empty.description")}
      />
    );
  }

  return (
    <div className="grid grid-cols-1 items-stretch gap-4 p-4 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map((card) => (
        <PropertyCard key={card.propertyId} card={card} />
      ))}
    </div>
  );
}
