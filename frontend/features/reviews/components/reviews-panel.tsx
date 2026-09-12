"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type {
  ReviewAction,
} from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import { useReviewsList } from "../hooks/use-reviews-data";
import { readErrorKey } from "../lib/reviews-error";
import { ReviewActions } from "./review-actions";
import { ReviewFilters } from "./review-filters";
import { ReviewRow } from "./review-row";
import { ReviewsPagination } from "./reviews-pagination";

/**
 * The Reseñas tab (R5.*). Lists all states, with a `status` selector on the
 * header. **Add review** is gated on `CREATE_REVIEW_UI` (D15, R7.1, R7.4):
 * the button itself does not render for a role without the permission —
 * R7.1's own user story is «ver los controles que me tocan y sólo esos».
 *
 * Renders `ReviewActions` per row with the legalActions matrix of D5 — the
 * same wiring pattern as DraftsPanel. The matrix filters out MARK_POSTED at
 * the row level (R4.2 reserved the dialog for that); in-row buttons cover
 * the open decision cases (APPROVE / IGNORE / EDIT) only.
 */
export interface ReviewsPanelProps {
  catalog: ReadonlyArray<{ id: string; name: string; internalCode: string }>;
  catalogPending: boolean;
  /** Gates whether the Add review button renders at all (D15, R7.1, R7.4). */
  canCreate: boolean;
  createDialogOpen: boolean;
  onOpenCreateDialog: () => void;
  onOpenRow: (reviewId: string) => void;
  /** The current user's role for the action matrix (D5). */
  role: "owner" | "manager" | "other";
  /** Set by the parent so we can refresh the listings after a mutation. */
  isMutationPending: boolean;
  /**
   * The id of the review whose mutation is currently in flight, or `null`.
   * Lets each row's `ReviewActions` show its own "Enviando…" (D9) instead of
   * every row reporting `false` regardless of which one is actually pending.
   */
  pendingReviewId: string | null;
  /** Mutation handler wired through the parent (R3.1). */
  onConfirm: (input: {
    reviewId: string;
    action: Exclude<ReviewAction, "MARK_POSTED">;
    draftContent?: string;
  }) => void;
}

export function ReviewsPanel({
  catalog,
  catalogPending,
  canCreate,
  createDialogOpen,
  onOpenCreateDialog,
  onOpenRow,
  role,
  isMutationPending,
  pendingReviewId,
  onConfirm,
}: ReviewsPanelProps) {
  const { t } = useTranslation("reviews");
  const slice = useReviewsUiStore((state) => state.reviews);
  const setPropertyId = useReviewsUiStore((s) => s.setReviewsPropertyId);
  const setChannel = useReviewsUiStore((s) => s.setReviewsChannel);
  const setSentiment = useReviewsUiStore((s) => s.setReviewsSentiment);
  const setStatus = useReviewsUiStore((s) => s.setReviewsStatus);
  const setRatingMin = useReviewsUiStore((s) => s.setReviewsRatingMin);
  const setRatingMax = useReviewsUiStore((s) => s.setReviewsRatingMax);
  const setDateFrom = useReviewsUiStore((s) => s.setReviewsDateFrom);
  const setDateTo = useReviewsUiStore((s) => s.setReviewsDateTo);
  const setPage = useReviewsUiStore((s) => s.setReviewsPage);

  const filters = {
    ...(slice.propertyId !== undefined ? { propertyId: slice.propertyId } : {}),
    ...(slice.channel !== undefined ? { channel: slice.channel } : {}),
    ...(slice.sentiment !== undefined ? { sentiment: slice.sentiment } : {}),
    ...(slice.status !== undefined ? { status: slice.status } : {}),
    ...(slice.ratingMin !== undefined
      ? { ratingMin: Number(slice.ratingMin) }
      : {}),
    ...(slice.ratingMax !== undefined
      ? { ratingMax: Number(slice.ratingMax) }
      : {}),
    ...(slice.dateFrom !== undefined ? { dateFrom: slice.dateFrom } : {}),
    ...(slice.dateTo !== undefined ? { dateTo: slice.dateTo } : {}),
  };
  const query = useReviewsList(filters, slice.page);

  return (
    <div className="flex flex-col gap-3" data-testid="reviews-panel">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-headline-md font-semibold text-foreground">
          {t("list.label")}
        </h2>
        {canCreate && !createDialogOpen && (
          <Button type="button" onClick={onOpenCreateDialog}>
            {t("create.button")}
          </Button>
        )}
      </div>
      <ReviewFilters
        catalog={catalog}
        propertyId={slice.propertyId}
        onPropertyIdChange={setPropertyId}
        channel={slice.channel}
        onChannelChange={setChannel}
        sentiment={slice.sentiment}
        onSentimentChange={setSentiment}
        ratingMin={slice.ratingMin}
        onRatingMinChange={setRatingMin}
        ratingMax={slice.ratingMax}
        onRatingMaxChange={setRatingMax}
        dateFrom={slice.dateFrom}
        onDateFromChange={setDateFrom}
        dateTo={slice.dateTo}
        onDateToChange={setDateTo}
        status={slice.status}
        onStatusChange={setStatus}
      />
      {query.isPending && (
        <p className="text-body-base text-muted-foreground">{t("list.loading")}</p>
      )}
      {query.isError && (
        <p role="status" aria-live="polite" className="text-body-base text-destructive">
          {t(readErrorKey(query.error))}
        </p>
      )}
      {query.data && query.data.total === 0 && (
        <p className="text-body-base text-muted-foreground">
          {t("list.empty.title")}
        </p>
      )}
      {query.data && query.data.total > 0 && (
        <>
          <ul className="flex flex-col">
            {query.data.items.map((review) => (
              <li key={review.id} className="flex flex-col gap-2 border-b border-border py-2">
                <ReviewRow
                  review={review}
                  catalog={catalog}
                  catalogPending={catalogPending}
                  showStatus={true}
                  onOpen={onOpenRow}
                />
                <ReviewActions
                  reviewId={review.id}
                  status={review.status}
                  role={role}
                  isBusy={isMutationPending}
                  isPending={pendingReviewId === review.id}
                  onConfirm={(input) =>
                    onConfirm({
                      reviewId: input.reviewId,
                      action: input.action,
                    })
                  }
                />
              </li>
            ))}
          </ul>
          <ReviewsPagination
            page={slice.page}
            totalPages={query.data.totalPages}
            total={query.data.total}
            onPageChange={setPage}
            labelKey="pagination.label"
          />
        </>
      )}
    </div>
  );
}