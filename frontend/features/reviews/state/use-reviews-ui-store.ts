"use client";

import { create } from "zustand";

import type {
  ReviewChannel,
  ReviewSentiment,
  ReviewStatus,
} from "../data";

/**
 * Lightweight UI state for the reviews screen (`steering/frontend.md`: Zustand
 * is for UI state only). It holds ONLY the selected values, the active tab,
 * and the open detail id — never reviews, drafts, or the property catalog,
 * which are server state owned by TanStack Query.
 *
 * **The reset to page 1 lives inside the setters** (design D14, inherited from
 * `use-pricing-ui-store.ts`): it is an invariant of the store, not a courtesy
 * each caller has to remember, so a filter change can never leave a page
 * offset inherited from the previous filter and show an empty page nobody asked
 * for.
 *
 * For the same reason the store records **which tenant its filters belong to**.
 * A module-level singleton outlives the view and outlives the session: a
 * `propertyId` chosen by one session would otherwise be re-sent on the next
 * session's first request, carrying one tenant's opaque identifier into
 * another's (`steering/security.md` rule 1, frontend side). A component-scoped
 * ref cannot catch that, because logging out unmounts the view — so the
 * ownership has to live exactly where the filters live.
 *
 * **The two slices share nothing, not even `propertyId`** (design D14). Sharing
 * the page would be an obvious bug — page 3 of Borradores when you open
 * Reseñas. Sharing the property is a subtler bug: the Borradores slice always
 * carries `status = DRAFTED` (R2.1) and the Reseñas slice carries whatever
 * status the selector says, and the two lists are different shapes anyway.
 *
 * **`setActiveTab` closes the detail** (design D14, R1.3): a detail open over
 * Borradores does not make sense over Reseñas. Switching tabs discards the
 * detail's id; opening a new one is the explicit next action.
 */

export type ReviewsTab = "drafts" | "reviews";

export interface DraftsSlice {
  propertyId?: string;
  channel?: ReviewChannel;
  sentiment?: ReviewSentiment | null;
  ratingMin?: string;
  ratingMax?: string;
  dateFrom?: string;
  dateTo?: string;
  page: number;
}

export interface ReviewsSlice {
  propertyId?: string;
  channel?: ReviewChannel;
  sentiment?: ReviewSentiment | null;
  status?: ReviewStatus;
  ratingMin?: string;
  ratingMax?: string;
  dateFrom?: string;
  dateTo?: string;
  page: number;
}

export interface ReviewsUiState {
  /** The tenant these filters were chosen in; `undefined` until one adopts them. */
  tenantId?: string;
  activeTab: ReviewsTab;
  /** The id of the review whose detail is open above the list; `null` when closed. */
  detailReviewId: string | null;
  drafts: DraftsSlice;
  reviews: ReviewsSlice;

  /** Records the current tenant, discarding filters chosen in a different one. */
  adoptTenant: (tenantId?: string) => void;
  /** Switching tabs closes any open detail (D14). */
  setActiveTab: (tab: ReviewsTab) => void;
  setDetailReviewId: (reviewId: string | null) => void;

  setDraftsPropertyId: (value?: string) => void;
  setDraftsChannel: (value?: ReviewChannel) => void;
  setDraftsSentiment: (value?: ReviewSentiment | null) => void;
  setDraftsRatingMin: (value?: string) => void;
  setDraftsRatingMax: (value?: string) => void;
  setDraftsDateFrom: (value?: string) => void;
  setDraftsDateTo: (value?: string) => void;
  setDraftsPage: (page: number) => void;

  setReviewsPropertyId: (value?: string) => void;
  setReviewsChannel: (value?: ReviewChannel) => void;
  setReviewsSentiment: (value?: ReviewSentiment | null) => void;
  setReviewsStatus: (value?: ReviewStatus) => void;
  setReviewsRatingMin: (value?: string) => void;
  setReviewsRatingMax: (value?: string) => void;
  setReviewsDateFrom: (value?: string) => void;
  setReviewsDateTo: (value?: string) => void;
  setReviewsPage: (page: number) => void;

  reset: () => void;
}

const INITIAL = {
  tenantId: undefined,
  activeTab: "drafts",
  detailReviewId: null,
  drafts: {
    propertyId: undefined,
    channel: undefined,
    sentiment: undefined,
    ratingMin: undefined,
    ratingMax: undefined,
    dateFrom: undefined,
    dateTo: undefined,
    page: 1,
  },
  reviews: {
    propertyId: undefined,
    channel: undefined,
    sentiment: undefined,
    status: undefined,
    ratingMin: undefined,
    ratingMax: undefined,
    dateFrom: undefined,
    dateTo: undefined,
    page: 1,
  },
} as const satisfies Pick<
  ReviewsUiState,
  "tenantId" | "activeTab" | "detailReviewId" | "drafts" | "reviews"
>;

export const useReviewsUiStore = create<ReviewsUiState>((set) => ({
  ...INITIAL,

  adoptTenant: (tenantId) =>
    set((current) =>
      current.tenantId === tenantId ? current : { ...INITIAL, tenantId },
    ),
  setActiveTab: (activeTab) => set({ activeTab, detailReviewId: null }),
  setDetailReviewId: (detailReviewId) => set({ detailReviewId }),

  setDraftsPropertyId: (propertyId) =>
    set((current) => ({ drafts: { ...current.drafts, propertyId, page: 1 } })),
  setDraftsChannel: (channel) =>
    set((current) => ({ drafts: { ...current.drafts, channel, page: 1 } })),
  setDraftsSentiment: (sentiment) =>
    set((current) => ({ drafts: { ...current.drafts, sentiment, page: 1 } })),
  setDraftsRatingMin: (ratingMin) =>
    set((current) => ({ drafts: { ...current.drafts, ratingMin, page: 1 } })),
  setDraftsRatingMax: (ratingMax) =>
    set((current) => ({ drafts: { ...current.drafts, ratingMax, page: 1 } })),
  setDraftsDateFrom: (dateFrom) =>
    set((current) => ({ drafts: { ...current.drafts, dateFrom, page: 1 } })),
  setDraftsDateTo: (dateTo) =>
    set((current) => ({ drafts: { ...current.drafts, dateTo, page: 1 } })),
  setDraftsPage: (page) =>
    set((current) => ({ drafts: { ...current.drafts, page } })),

  setReviewsPropertyId: (propertyId) =>
    set((current) => ({
      reviews: { ...current.reviews, propertyId, page: 1 },
    })),
  setReviewsChannel: (channel) =>
    set((current) => ({ reviews: { ...current.reviews, channel, page: 1 } })),
  setReviewsSentiment: (sentiment) =>
    set((current) => ({ reviews: { ...current.reviews, sentiment, page: 1 } })),
  setReviewsStatus: (status) =>
    set((current) => ({ reviews: { ...current.reviews, status, page: 1 } })),
  setReviewsRatingMin: (ratingMin) =>
    set((current) => ({ reviews: { ...current.reviews, ratingMin, page: 1 } })),
  setReviewsRatingMax: (ratingMax) =>
    set((current) => ({ reviews: { ...current.reviews, ratingMax, page: 1 } })),
  setReviewsDateFrom: (dateFrom) =>
    set((current) => ({ reviews: { ...current.reviews, dateFrom, page: 1 } })),
  setReviewsDateTo: (dateTo) =>
    set((current) => ({ reviews: { ...current.reviews, dateTo, page: 1 } })),
  setReviewsPage: (page) =>
    set((current) => ({ reviews: { ...current.reviews, page } })),

  reset: () => set({ ...INITIAL }),
}));