"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type {
  ReviewAction,
  ReviewChannel,
  ReviewStatus,
} from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import { useReviewsList } from "../hooks/use-reviews-data";
import { ReviewActions } from "./review-actions";
import { ReviewRow } from "./review-row";
import { ReviewsPagination } from "./reviews-pagination";

/**
 * The Reseñas tab (R5.*). Lists all states, with a `status` selector on the
 * header. **Add review** is gated on `CREATE_REVIEW_UI` (D15) at the parent.
 *
 * Renders `ReviewActions` per row with the legalActions matrix of D5 — the
 * same wiring pattern as DraftsPanel. The matrix filters out MARK_POSTED at
 * the row level (R4.2 reserved the dialog for that); in-row buttons cover
 * the open decision cases (APPROVE / IGNORE / EDIT) only.
 */
export interface ReviewsPanelProps {
  catalog: ReadonlyArray<{ id: string; name: string; internalCode: string }>;
  catalogPending: boolean;
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

const STATUSES: readonly ReviewStatus[] = [
  "NEW",
  "DRAFTED",
  "APPROVED",
  "POSTED_MANUALLY",
  "IGNORED",
] as const;

const CHANNELS: readonly ReviewChannel[] = [
  "AIRBNB",
  "BOOKING",
  "GOOGLE",
  "MANUAL",
  "OTHER",
] as const;

export function ReviewsPanel({
  catalog,
  catalogPending,
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
  const setStatus = useReviewsUiStore((s) => s.setReviewsStatus);
  const setPage = useReviewsUiStore((s) => s.setReviewsPage);

  const filters = {
    ...(slice.propertyId !== undefined ? { propertyId: slice.propertyId } : {}),
    ...(slice.channel !== undefined ? { channel: slice.channel } : {}),
    ...(slice.status !== undefined ? { status: slice.status } : {}),
  };
  const query = useReviewsList(filters, slice.page);

  return (
    <div className="flex flex-col gap-3" data-testid="reviews-panel">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-headline-md font-semibold text-foreground">
          {t("list.label")}
        </h2>
        {!createDialogOpen && (
          <Button type="button" onClick={onOpenCreateDialog}>
            {t("create.button")}
          </Button>
        )}
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-body-base">
          <span className="font-medium text-foreground">
            {t("filters.property.label")}
          </span>
          <select
            value={slice.propertyId ?? ""}
            onChange={(e) =>
              setPropertyId(e.target.value === "" ? undefined : e.target.value)
            }
            className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
          >
            <option value="">{t("filters.property.all")}</option>
            {catalog.map((property) => (
              <option key={property.id} value={property.id}>
                {property.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-base">
          <span className="font-medium text-foreground">
            {t("filters.channel.label")}
          </span>
          <select
            value={slice.channel ?? ""}
            onChange={(e) =>
              setChannel(
                e.target.value === ""
                  ? undefined
                  : (e.target.value as ReviewChannel),
              )
            }
            className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
          >
            <option value="">{t("filters.channel.all")}</option>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {t(`channel.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-base">
          <span className="font-medium text-foreground">
            {t("filters.status.label")}
          </span>
          <select
            value={slice.status ?? ""}
            onChange={(e) =>
              setStatus(
                e.target.value === ""
                  ? undefined
                  : (e.target.value as ReviewStatus),
              )
            }
            className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
          >
            <option value="">{t("filters.status.all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`status.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {query.isPending && (
        <p className="text-body-base text-muted-foreground">{t("list.loading")}</p>
      )}
      {query.isError && (
        <p className="text-body-base text-destructive">
          {t("list.error.title")}
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