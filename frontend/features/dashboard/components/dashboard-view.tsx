"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import { useBlockedTransitions } from "../stalls";
import { useDashboardCards } from "../hooks/use-dashboard-data";
import { PropertyCard } from "./property-card";

/**
 * Client view for `/dashboard` (PRD §9.1). It consumes `useDashboardCards` and
 * renders the cross-cutting loading/error/empty states from the shell, then a
 * responsive grid of `PropertyCard`. It never exposes raw error detail — the
 * error copy is localized and retry re-runs the query.
 *
 * `useBlockedTransitions` is mounted once at the dashboard level and sliced
 * per card by `propertyId` (proposal `blocked-transitions-web` D1). The query
 * is **never** invoked inside `PropertyCard`: a per-card fetch would be the
 * N+1 the design rejects. If the stalls query is still pending, the cards
 * render with no stalls slice (R1.4) — the section is omitted, the rest of
 * the card renders unchanged.
 */
export function DashboardView() {
  const { t } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const cardsQuery = useDashboardCards();
  const stallsQuery = useBlockedTransitions();

  if (cardsQuery.isPending) {
    return <LoadingState label={tStates("loading.label")} />;
  }

  if (cardsQuery.isError) {
    return (
      <ErrorState
        title={t("cards.error.title")}
        description={t("cards.error.description")}
        onRetry={() => void cardsQuery.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }

  const cards = cardsQuery.data.data;
  if (cards.length === 0) {
    return (
      <EmptyState
        title={t("cards.empty.title")}
        description={t("cards.empty.description")}
      />
    );
  }

  const stallsByPropertyId = stallsQuery.isSuccess
    ? stallsQuery.byPropertyId
    : new Map();

  return (
    <div className="grid grid-cols-1 items-stretch gap-4 p-4 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map((card) => (
        <PropertyCard
          key={card.propertyId}
          card={card}
          stalls={stallsByPropertyId.get(card.propertyId) ?? []}
        />
      ))}
    </div>
  );
}
