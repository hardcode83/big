"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { Review, ReviewAction, ReviewStatus } from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import { useReviewsList } from "../hooks/use-reviews-data";
import { readErrorKey } from "../lib/reviews-error";
import { ReviewActions } from "./review-actions";
import { ReviewFilters } from "./review-filters";
import { ReviewRow } from "./review-row";
import { ReviewsPagination } from "./reviews-pagination";

/**
 * The Borradores tab (R2.*). Always filters to `status = DRAFTED` — there is
 * no `status` selector on this tab, because the only state that belongs here
 * is `DRAFTED` and offering other states would mean this tab is not the
 * decision queue the roadmap asked for (proposal "Una cola de borradores
 * con decisión").
 *
 * **Add review** is gated on `CREATE_REVIEW_UI` (D15, R7.1, R7.4): the button
 * itself does not render for a role without the permission — R7.1's own user
 * story is «ver los controles que me tocan y sólo esos», so a role without
 * `CREATE_REVIEW_UI` must not be offered a button at all, not merely a
 * disabled or inert one.
 */
export interface DraftsPanelProps {
  catalog: ReadonlyArray<{ id: string; name: string; internalCode: string }>;
  catalogPending: boolean;
  /** Gates whether the Add review button renders at all (D15, R7.1, R7.4). */
  canCreate: boolean;
  /** Is the create-review dialog currently open? */
  createDialogOpen: boolean;
  /** Open the create-review dialog. */
  onOpenCreateDialog: () => void;
  /** Set by the parent so we can refresh the listings after a mutation. */
  isMutationPending: boolean;
  /**
   * The id of the review whose mutation is currently in flight, or `null`.
   * Lets each row's `ReviewActions` show its own "Enviando…" (D9) instead of
   * every row reporting `false` regardless of which one is actually pending.
   */
  pendingReviewId: string | null;
  onOpenRow: (reviewId: string) => void;
  /** The current user's role for the action matrix (D5). */
  role: "owner" | "manager" | "other";
  /** Mutation handler wired through the parent (R3.1). */
  onConfirm: (input: {
    reviewId: string;
    action: Exclude<ReviewAction, "MARK_POSTED">;
    draftContent?: string;
  }) => void;
}

export function DraftsPanel({
  catalog,
  catalogPending,
  canCreate,
  createDialogOpen,
  onOpenCreateDialog,
  isMutationPending,
  pendingReviewId,
  onOpenRow,
  role,
  onConfirm,
}: DraftsPanelProps) {
  const { t } = useTranslation("reviews");
  const slice = useReviewsUiStore((state) => state.drafts);
  const setPropertyId = useReviewsUiStore((s) => s.setDraftsPropertyId);
  const setChannel = useReviewsUiStore((s) => s.setDraftsChannel);
  const setSentiment = useReviewsUiStore((s) => s.setDraftsSentiment);
  const setRatingMin = useReviewsUiStore((s) => s.setDraftsRatingMin);
  const setRatingMax = useReviewsUiStore((s) => s.setDraftsRatingMax);
  const setDateFrom = useReviewsUiStore((s) => s.setDraftsDateFrom);
  const setDateTo = useReviewsUiStore((s) => s.setDraftsDateTo);
  const setPage = useReviewsUiStore((s) => s.setDraftsPage);

  /** The Borradores filter is always `status = DRAFTED`. It is not a selector. */
  const filters = {
    ...(slice.propertyId !== undefined ? { propertyId: slice.propertyId } : {}),
    ...(slice.channel !== undefined ? { channel: slice.channel } : {}),
    ...(slice.sentiment !== undefined ? { sentiment: slice.sentiment } : {}),
    ...(slice.ratingMin !== undefined
      ? { ratingMin: Number(slice.ratingMin) }
      : {}),
    ...(slice.ratingMax !== undefined
      ? { ratingMax: Number(slice.ratingMax) }
      : {}),
    ...(slice.dateFrom !== undefined ? { dateFrom: slice.dateFrom } : {}),
    ...(slice.dateTo !== undefined ? { dateTo: slice.dateTo } : {}),
    status: "DRAFTED" as ReviewStatus,
  };
  const query = useReviewsList(filters, slice.page);

  return (
    <div className="flex flex-col gap-3" data-testid="drafts-panel">
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
          {t("list.draftsEmpty.title")}
        </p>
      )}
      {query.data && query.data.total > 0 && (
        <>
          <ul className="flex flex-col">
            {query.data.items.map((review: Review) => (
              <li key={review.id} className="flex flex-col gap-2 border-b border-border py-2">
                <ReviewRow
                  review={review}
                  catalog={catalog}
                  catalogPending={catalogPending}
                  showStatus={false}
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
            labelKey="pagination.drafts"
          />
        </>
      )}
    </div>
  );
}