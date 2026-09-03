"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useHasPermission } from "@/lib/auth";

import type {
  DecisionStatus,
  GenerationReport,
  PropertySummary,
} from "../data";
import { useRecommendations } from "../hooks/use-pricing-data";
import { decideErrorKey, generateErrorKey, readErrorKey } from "../lib/pricing-error";
import type { PropertyDirectory } from "../lib/property-directory";
import { usePricingUiStore } from "../state/use-pricing-ui-store";
import { PricingPagination } from "./pricing-pagination";
import { RecommendationFilters } from "./recommendation-filters";
import { RecommendationRow } from "./recommendation-row";

/**
 * The decision queue (R2, R3, R4). Filters, the regeneration button, one live
 * region, the list, and pagination.
 *
 * **There is exactly one live region** (`role="status" aria-live="polite"`,
 * design D8), present from the first render so a screen reader is already
 * observing it when the first result lands. Two regions would be two places that
 * might have spoken; it is also why only one write may be in flight at a time.
 *
 * Loading, error and empty are tied to the **recommendations** query alone. A
 * catalog that fails does not reach `ErrorState` (R2.8): the price, the night and
 * the status have already arrived, and they are what the screen is for.
 */
export interface RecommendationsPanelProps {
  properties: PropertyDirectory<PropertySummary>;
  propertyList: readonly PropertySummary[];
  filters: {
    propertyId?: string;
    dateFrom?: string;
    dateTo?: string;
    status?: ReturnType<typeof usePricingUiStore.getState>["recommendations"]["status"];
  };
  page: number;
  onPageChange: (page: number) => void;
  decide: {
    isPending: boolean;
    variables?: { recommendationId: string };
    isError: boolean;
    error: unknown;
    mutate: (input: {
      recommendationId: string;
      status: DecisionStatus;
    }) => void;
  };
  generate: {
    isPending: boolean;
    isError: boolean;
    isSuccess: boolean;
    error: unknown;
    data?: GenerationReport;
    mutate: () => void;
  };
  isBusy: boolean;
}

export function RecommendationsPanel({
  properties,
  propertyList,
  filters,
  page,
  onPageChange,
  decide,
  generate,
  isBusy,
}: RecommendationsPanelProps) {
  const { t } = useTranslation("pricing");
  const { t: tStates } = useTranslation("states");
  const canDecide = useHasPermission("MANAGE_PRICE_RECOMMENDATIONS");
  const query = useRecommendations(filters, page);

  /**
   * What the single live region says. A failure is marked `alert` inside the
   * same region, the way `cleaning-view.tsx` does it. Every failure text is
   * chosen by HTTP status and never taken from the backend body (R3.7).
   */
  function announcement(): ReactNode {
    if (decide.isPending) {
      return t("decide.sending");
    }
    if (generate.isPending) {
      return t("generate.sending");
    }
    if (decide.isError) {
      return <span role="alert">{t(decideErrorKey(decide.error))}</span>;
    }
    if (generate.isError) {
      return <span role="alert">{t(generateErrorKey(generate.error))}</span>;
    }
    if (generate.isSuccess && generate.data) {
      // The four counters and nothing else: the contract exposes no `failed`,
      // so no claim of completeness or correctness may be made (R4.3).
      return t("generate.report", { ...generate.data });
    }
    return null;
  }

  function body() {
    if (query.isPending) {
      return <LoadingState label={tStates("loading.label")} />;
    }
    if (query.isError) {
      return (
        <ErrorState
          title={t("recommendations.list.error.title")}
          // A 403 says something a retry will never change (design D9, D17).
          description={t(readErrorKey(query.error))}
          onRetry={() => void query.refetch()}
          retryLabel={tStates("error.retry")}
        />
      );
    }

    const { items, total, page: current, totalPages } = query.data;
    if (total === 0) {
      // Before any pagination is considered, so «página 1 de 0» is unreachable.
      return (
        <EmptyState
          title={t("recommendations.list.empty.title")}
          description={t("recommendations.list.empty.description")}
        />
      );
    }

    return (
      <>
        <ul
          aria-label={t("recommendations.list.label")}
          className="grid grid-cols-1 items-stretch gap-4 p-4 xl:grid-cols-2"
        >
          {items.map((recommendation) => (
            <RecommendationRow
              key={recommendation.id}
              recommendation={recommendation}
              properties={properties}
              decision={{
                isPending:
                  decide.isPending &&
                  decide.variables?.recommendationId === recommendation.id,
                isBusy,
                onConfirm: decide.mutate,
              }}
            />
          ))}
        </ul>
        <PricingPagination
          page={current}
          totalPages={totalPages}
          total={total}
          onPageChange={onPageChange}
        />
      </>
    );
  }

  return (
    <div className="flex min-w-0 flex-col">
      <RecommendationFilters properties={propertyList} />

      {canDecide ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <Button
            type="button"
            variant="outline"
            disabled={isBusy}
            onClick={() => generate.mutate()}
          >
            {generate.isPending ? t("generate.sending") : t("generate.button")}
          </Button>
        </div>
      ) : null}

      {/* The single live region of design D8. */}
      <div
        role="status"
        aria-live="polite"
        className="px-4 py-2 text-body-base text-muted-foreground empty:hidden"
      >
        {announcement()}
      </div>

      {body()}
    </div>
  );
}
