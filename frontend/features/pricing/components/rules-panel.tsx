"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { PricingRuleFilters, PropertySummary } from "../data";
import { usePricingRules } from "../hooks/use-pricing-data";
import { readErrorKey } from "../lib/pricing-error";
import type { PropertyDirectory } from "../lib/property-directory";
import { PricingPagination } from "./pricing-pagination";
import { RuleFilters } from "./rule-filters";
import { RuleRow } from "./rule-row";

/**
 * The rules tab: read-only (R5). Filters, list, empty state, error state and
 * pagination — and no write of any kind.
 *
 * **Nothing here calls `GET /api/v1/pricing-rules/{rule_id}`** (R5.5). It could
 * not: `PricingDataSource` declares no such method, because the detail route
 * returns the same `PricingRuleResponse` already carried by every `items[]`.
 *
 * Rule CRUD is out of scope by its own roadmap entry — the form would drag in the
 * whole of PRD §7.17's validation, which the backend enforces in the domain and
 * not in the request schema, and the frontend may not paint the `422` body to say
 * which of the five JSONB columns failed.
 */
export interface RulesPanelProps {
  properties: PropertyDirectory<PropertySummary>;
  propertyList: readonly PropertySummary[];
  filters: PricingRuleFilters;
  page: number;
  onPageChange: (page: number) => void;
}

export function RulesPanel({
  properties,
  propertyList,
  filters,
  page,
  onPageChange,
}: RulesPanelProps) {
  const { t } = useTranslation("pricing");
  const { t: tStates } = useTranslation("states");
  const query = usePricingRules(filters, page);

  function body() {
    if (query.isPending) {
      return <LoadingState label={tStates("loading.label")} />;
    }
    if (query.isError) {
      return (
        <ErrorState
          title={t("rules.list.error.title")}
          description={t(readErrorKey(query.error))}
          onRetry={() => void query.refetch()}
          retryLabel={tStates("error.retry")}
        />
      );
    }

    const { items, total, page: current, totalPages } = query.data;
    if (total === 0) {
      return (
        <EmptyState
          title={t("rules.list.empty.title")}
          description={t("rules.list.empty.description")}
        />
      );
    }

    return (
      <>
        <ul
          aria-label={t("rules.list.label")}
          className="grid grid-cols-1 gap-4 p-4 xl:grid-cols-2"
        >
          {items.map((rule) => (
            <RuleRow key={rule.id} rule={rule} properties={properties} />
          ))}
        </ul>
        <PricingPagination
          page={current}
          totalPages={totalPages}
          total={total}
          onPageChange={onPageChange}
          labelKey="rules.pagination.label"
        />
      </>
    );
  }

  return (
    <div className="flex min-w-0 flex-col">
      <RuleFilters properties={propertyList} />
      {body()}
    </div>
  );
}
