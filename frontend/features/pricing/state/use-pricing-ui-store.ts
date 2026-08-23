"use client";

import { create } from "zustand";

import type { PriceRecommendationStatus } from "../data";

/**
 * Lightweight UI state for the pricing screen (`steering/frontend.md`: Zustand is
 * for UI state only). It holds ONLY the selected values and the active tab —
 * never recommendations or rules, which are server state owned by TanStack Query.
 *
 * **The reset to page 1 lives inside the setters** (design D11, inherited from
 * `use-cleaning-filters-store.ts`): it is an invariant of the store, not a
 * courtesy each caller has to remember, so a filter change can never leave a page
 * offset inherited from the previous filter and show an empty page nobody asked
 * for.
 *
 * For the same reason the store records **which tenant its filters belong to**.
 * Being a module-level singleton it outlives the view and outlives the session: a
 * `propertyId` chosen by one session would otherwise be re-sent on the next
 * session's first request, carrying one tenant's opaque identifier into another's
 * (`steering/security.md` rule 1, frontend side). A component-scoped ref cannot
 * catch that, because logging out unmounts the view — so the ownership has to
 * live exactly where the filters live.
 *
 * **The two slices share nothing, not even `propertyId`** (design D11). Sharing
 * the page would be an obvious bug — page 3 of recommendations when you open
 * Rules. Sharing the property is a subtler and worse one: R4.1 sends «the active
 * filter's `property_id`» to `POST /generate`, so if that filter had last been
 * set from the Rules tab, a regeneration would silently sweep a different scope
 * from the one the user is looking at.
 */
export type PricingTab = "recommendations" | "rules";

export interface RecommendationSlice {
  propertyId?: string;
  dateFrom?: string;
  dateTo?: string;
  status?: PriceRecommendationStatus;
  page: number;
}

export interface RuleSlice {
  propertyId?: string;
  active?: boolean;
  page: number;
}

export interface PricingUiState {
  /** The tenant these filters were chosen in; `undefined` until one adopts them. */
  tenantId?: string;
  activeTab: PricingTab;
  recommendations: RecommendationSlice;
  rules: RuleSlice;

  /** Records the current tenant, discarding filters chosen in a different one. */
  adoptTenant: (tenantId?: string) => void;
  /** Switching tabs touches no slice: each keeps its own filters and page. */
  setActiveTab: (tab: PricingTab) => void;

  setRecommendationPropertyId: (value?: string) => void;
  setRecommendationDateFrom: (value?: string) => void;
  setRecommendationDateTo: (value?: string) => void;
  setRecommendationStatus: (value?: PriceRecommendationStatus) => void;
  setRecommendationPage: (page: number) => void;

  setRulePropertyId: (value?: string) => void;
  setRuleActive: (value?: boolean) => void;
  setRulePage: (page: number) => void;

  reset: () => void;
}

// `tenantId` belongs in here so `reset()` really returns to the initial state: a
// store that kept its recorded tenant across a reset would claim filters it no
// longer holds, and would make any test that resets order-dependent.
const INITIAL = {
  tenantId: undefined,
  activeTab: "recommendations",
  recommendations: {
    propertyId: undefined,
    dateFrom: undefined,
    dateTo: undefined,
    status: undefined,
    page: 1,
  },
  rules: { propertyId: undefined, active: undefined, page: 1 },
} as const satisfies Pick<
  PricingUiState,
  "tenantId" | "activeTab" | "recommendations" | "rules"
>;

export const usePricingUiStore = create<PricingUiState>((set) => ({
  ...INITIAL,

  adoptTenant: (tenantId) =>
    set((current) =>
      current.tenantId === tenantId ? current : { ...INITIAL, tenantId },
    ),
  setActiveTab: (activeTab) => set({ activeTab }),

  setRecommendationPropertyId: (propertyId) =>
    set((current) => ({
      recommendations: { ...current.recommendations, propertyId, page: 1 },
    })),
  setRecommendationDateFrom: (dateFrom) =>
    set((current) => ({
      recommendations: { ...current.recommendations, dateFrom, page: 1 },
    })),
  setRecommendationDateTo: (dateTo) =>
    set((current) => ({
      recommendations: { ...current.recommendations, dateTo, page: 1 },
    })),
  setRecommendationStatus: (status) =>
    set((current) => ({
      recommendations: { ...current.recommendations, status, page: 1 },
    })),
  setRecommendationPage: (page) =>
    set((current) => ({ recommendations: { ...current.recommendations, page } })),

  setRulePropertyId: (propertyId) =>
    set((current) => ({ rules: { ...current.rules, propertyId, page: 1 } })),
  setRuleActive: (active) =>
    set((current) => ({ rules: { ...current.rules, active, page: 1 } })),
  setRulePage: (page) => set((current) => ({ rules: { ...current.rules, page } })),

  reset: () => set({ ...INITIAL }),
}));
