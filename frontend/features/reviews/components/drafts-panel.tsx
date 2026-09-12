"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { Review, ReviewAction, ReviewStatus } from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import { useReviewsList } from "../hooks/use-reviews-data";
import { ReviewActions } from "./review-actions";
import { ReviewRow } from "./review-row";
import { ReviewsPagination } from "./reviews-pagination";

/**
 * The Borradores tab (R2.*). Always filters to `status = DRAFTED` — there is
 * no `status` selector on this tab, because the only state that belongs here
 * is `DRAFTED` and offering other states would mean this tab is not the
 * decision queue the roadmap asked for (proposal "Una cola de borradores
 * con decisión").
 *
 * **Add review** is gated on `CREATE_REVIEW_UI` (D15). The button opens
 * `CreateReviewDialog` from the view, not here — the panel only knows
 * whether the button is enabled.
 */
export interface DraftsPanelProps {
  catalog: ReadonlyArray<{ id: string; name: string; internalCode: string }>;
  catalogPending: boolean;
  /** Is the create-review dialog currently open? */
  createDialogOpen: boolean;
  /** Open the create-review dialog. */
  onOpenCreateDialog: () => void;
  /** Set by the parent so we can refresh the listings after a mutation. */
  isMutationPending: boolean;
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
  createDialogOpen,
  onOpenCreateDialog,
  isMutationPending,
  onOpenRow,
  role,
  onConfirm,
}: DraftsPanelProps) {
  const { t } = useTranslation("reviews");
  const slice = useReviewsUiStore((state) => state.drafts);
  const setPropertyId = useReviewsUiStore((s) => s.setDraftsPropertyId);
  const setPage = useReviewsUiStore((s) => s.setDraftsPage);

  /** The Borradores filter is always `status = DRAFTED`. It is not a selector. */
  const filters = {
    ...(slice.propertyId !== undefined ? { propertyId: slice.propertyId } : {}),
    status: "DRAFTED" as ReviewStatus,
  };
  const query = useReviewsList(filters, slice.page);

  return (
    <div className="flex flex-col gap-3" data-testid="drafts-panel">
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
      <label className="flex flex-col gap-1 text-body-base">
        <span className="font-medium text-foreground">{t("filters.property.label")}</span>
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
                  isPending={false}
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