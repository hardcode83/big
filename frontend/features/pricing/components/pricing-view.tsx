"use client";

import { useEffect } from "react";

import { useAuth } from "@/lib/auth";

import { useDecideRecommendation } from "../hooks/use-decide-recommendation";
import { useGenerateRecommendations } from "../hooks/use-generate-recommendations";
import { usePropertyDirectory } from "../hooks/use-pricing-data";
import { buildPropertyDirectory } from "../lib/property-directory";
import { usePricingUiStore } from "../state/use-pricing-ui-store";
import { PricingTabs } from "./pricing-tabs";
import { RecommendationsPanel } from "./recommendations-panel";
import { RulesPanel } from "./rules-panel";

/**
 * `/pricing` (PRD §24). It owns the two mutations, the tab, and the guard that
 * keeps one session's filters out of another's requests.
 *
 * **`isBusy` is the whole of design D8**: one write in flight at a time. Starting
 * a second mutation detaches the first and swallows its rejection, and R3.6/R3.8
 * make that rejection mandatory to show — plus there is a single live region, so
 * two writes would talk over each other. It disables the confirmation buttons and
 * the regeneration button, and **never a filter control**: disabling a focused
 * element drops focus to `<body>`.
 *
 * **`staleFilters` covers the first render** (design D11). The effect that adopts
 * the tenant runs only *after* it, so without this the first request would go out
 * carrying the previous session's filter — one tenant's opaque identifier in
 * another's query (`steering/security.md` rule 1, frontend side). The store owns
 * the invariant; the view reports who is looking and refuses filters that are not
 * theirs.
 *
 * Note the write path has its own equivalent guard inside
 * `use-generate-recommendations`, because that mutation reads the store directly
 * rather than through this component (design D7). Removing either does not leave
 * the other covering it.
 */
export function PricingView() {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? undefined;
  const {
    tenantId: filtersTenantId,
    activeTab,
    recommendations,
    rules,
    setActiveTab,
    setRecommendationPage,
    setRulePage,
    adoptTenant,
  } = usePricingUiStore();

  const staleFilters = filtersTenantId !== tenantId;
  useEffect(() => {
    adoptTenant(tenantId);
  }, [adoptTenant, tenantId]);

  const recommendationFilters = staleFilters
    ? {}
    : {
        ...(recommendations.propertyId !== undefined
          ? { propertyId: recommendations.propertyId }
          : {}),
        ...(recommendations.dateFrom !== undefined
          ? { dateFrom: recommendations.dateFrom }
          : {}),
        ...(recommendations.dateTo !== undefined
          ? { dateTo: recommendations.dateTo }
          : {}),
        ...(recommendations.status !== undefined
          ? { status: recommendations.status }
          : {}),
      };
  const ruleFilters = staleFilters
    ? {}
    : {
        ...(rules.propertyId !== undefined
          ? { propertyId: rules.propertyId }
          : {}),
        ...(rules.active !== undefined ? { active: rules.active } : {}),
      };
  const recommendationsPage = staleFilters ? 1 : recommendations.page;
  const rulesPage = staleFilters ? 1 : rules.page;

  const propertyDirectory = usePropertyDirectory();
  const properties = {
    index: buildPropertyDirectory(propertyDirectory.data),
    isPending: propertyDirectory.isPending,
  };
  const propertyList = propertyDirectory.data ?? [];

  const decide = useDecideRecommendation();
  const generate = useGenerateRecommendations();
  const isBusy = decide.isPending || generate.isPending;

  return (
    <PricingTabs activeTab={activeTab} onTabChange={setActiveTab}>
      {activeTab === "recommendations" ? (
        <RecommendationsPanel
          properties={properties}
          propertyList={propertyList}
          filters={recommendationFilters}
          page={recommendationsPage}
          onPageChange={setRecommendationPage}
          decide={decide}
          generate={generate}
          isBusy={isBusy}
        />
      ) : (
        <RulesPanel
          properties={properties}
          propertyList={propertyList}
          filters={ruleFilters}
          page={rulesPage}
          onPageChange={setRulePage}
        />
      )}
    </PricingTabs>
  );
}
