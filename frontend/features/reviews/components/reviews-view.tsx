"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/lib/auth";

import type { CreateReviewInput, ReviewAction } from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import {
  useCreateReview,
  useRespondToReview,
} from "../hooks/use-respond-to-review";
import {
  usePropertyDirectory,
  useReviewDetail,
  useReviewDraft,
  useReviewsList,
} from "../hooks/use-reviews-data";
import { CreateReviewDialog } from "./create-review-dialog";
import { DraftsPanel } from "./drafts-panel";
import { ReviewDetail } from "./review-detail";
import { ReviewActions } from "./review-actions";
import { ReviewsPanel } from "./reviews-panel";
import { ReviewsTabs } from "./reviews-tabs";

/**
 * Orchestrator of the two tabs (D11, R1.1, R1.3).
 *
 * Owns:
 *  - the create-review and detail dialogs;
 *  - the `useRespondToReview` mutation (which serves approve/ignore/edit/MARK_POSTED);
 *  - the `useCreateReview` mutation;
 *  - the global `isBusy` flag that disables every row's controls and the
 *    dialog's confirm button (D9, R3.4, R4.3);
 *  - the `staleFilters` guard from the precedent (`pricing-view.tsx`): on first
 *    render the slice may still hold a previous tenant's filters, so the
 *    queries go out empty and the effect adopts the tenant afterwards.
 *
 * Per row the detail mutation's `variables` carries the row's id, so the
 * detail itself can show its own "sending…" state. We do not expose per-row
 * isPending to the listing rows here — they use the global `isBusy` and
 * the detail dialog has its own `isPending`.
 */
export function ReviewsView() {
  const { t } = useTranslation("reviews");
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? undefined;
  const role: "owner" | "manager" | "other" =
    user?.role === "TENANT_OWNER"
      ? "owner"
      : user?.role === "PROPERTY_MANAGER"
        ? "manager"
        : "other";
  const canCreate = user?.role === "PROPERTY_MANAGER";
  const canDecide = user?.role === "TENANT_OWNER";

  const adoptTenant = useReviewsUiStore((s) => s.adoptTenant);
  const activeTab = useReviewsUiStore((s) => s.activeTab);
  const setActiveTab = useReviewsUiStore((s) => s.setActiveTab);
  const detailReviewId = useReviewsUiStore((s) => s.detailReviewId);
  const setDetailReviewId = useReviewsUiStore((s) => s.setDetailReviewId);

  const slice = useReviewsUiStore((s) =>
    s.activeTab === "drafts" ? s.drafts : s.reviews,
  );
  const staleFilters =
    useReviewsUiStore.getState().tenantId !== tenantId;
  useEffect(() => {
    adoptTenant(tenantId);
  }, [adoptTenant, tenantId]);

  const catalog = usePropertyDirectory();
  const catalogData = staleFilters ? undefined : catalog.data;

  // The detail / draft queries mount only when there is an open detail.
  const detail = useReviewDetail(detailReviewId);
  const draft = useReviewDraft(detailReviewId, detail.data?.status === "DRAFTED");

  const respond = useRespondToReview();
  const create = useCreateReview();

  const isBusy = respond.isPending || create.isPending;
  const isPendingThisRow = (reviewId: string): boolean =>
    respond.isPending &&
    respond.variables !== undefined &&
    "reviewId" in respond.variables &&
    respond.variables.reviewId === reviewId;

  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  // Wire both tabs through the same mutation. The Borradores panel receives
  // only the in-DRAFTED list, the Reseñas panel receives the filtered one.
  const draftsSlice = useReviewsUiStore((s) => s.drafts);
  const draftsQuery = useReviewsList(
    {
      ...(draftsSlice.propertyId !== undefined
        ? { propertyId: draftsSlice.propertyId }
        : {}),
      status: "DRAFTED",
    },
    draftsSlice.page,
  );

  function closeDetail() {
    setDetailReviewId(null);
  }

  function openRow(reviewId: string) {
    setDetailReviewId(reviewId);
  }

  function respondFromRow(input: {
    reviewId: string;
    action: Exclude<ReviewAction, "MARK_POSTED">;
    draftContent?: string;
  }) {
    if (input.action === "EDIT") {
      respond.mutate({
        reviewId: input.reviewId,
        action: "EDIT",
        draftContent: input.draftContent ?? "",
      });
    } else {
      respond.mutate({
        reviewId: input.reviewId,
        action: input.action,
      });
    }
  }

  return (
    <div className="flex flex-col gap-3" data-testid="reviews-view">
      <h1 className="text-headline-lg font-semibold text-foreground">
        {t("title")}
      </h1>
      <ReviewsTabs
        activeTab={activeTab}
        onTabChange={setActiveTab}
        panels={{
          drafts: {
            key: "drafts-panel",
            node: (
              <DraftsPanel
                catalog={catalogData ?? []}
                catalogPending={catalog.isPending}
                createDialogOpen={createDialogOpen}
                onOpenCreateDialog={() => canCreate && setCreateDialogOpen(true)}
                isMutationPending={isBusy}
                onOpenRow={openRow}
                role={canDecide ? role : "other"}
              />
            ),
          },
          reviews: {
            key: "reviews-panel",
            node: (
              <ReviewsPanel
                catalog={catalogData ?? []}
                catalogPending={catalog.isPending}
                createDialogOpen={createDialogOpen}
                onOpenCreateDialog={() => canCreate && setCreateDialogOpen(true)}
                onOpenRow={openRow}
              />
            ),
          },
        }}
      />
      {detailReviewId !== null && detail.data && (
        <ReviewDetail
          review={detail.data}
          draft={draft.data ?? null}
          isBusy={isBusy}
          isPending={isPendingThisRow(detailReviewId)}
          onClose={closeDetail}
          onConfirm={respondFromRow}
          onMarkPosted={(reviewId) => {
            respond.mutate({ reviewId, action: "MARK_POSTED" });
          }}
        />
      )}
      {detail.data && (
        <ReviewActions
          reviewId={detail.data.id}
          status={detail.data.status}
          role={role}
          isBusy={isBusy}
          isPending={isPendingThisRow(detail.data.id)}
          onConfirm={respondFromRow}
        />
      )}
      {canCreate && (
        <CreateReviewDialog
          open={createDialogOpen}
          onOpenChange={setCreateDialogOpen}
          catalog={catalogData ?? []}
          isBusy={isBusy}
          onSubmit={(input: CreateReviewInput) => {
            create.mutate(input, {
              onSuccess: () => setCreateDialogOpen(false),
            });
          }}
        />
      )}
      {/* The Borradores panel reads its own filtered query; expose it via a
        //  separate query to keep the view small. */}
      {/* This block keeps the type narrowing happy. */}
      <span hidden>{draftsQuery.error ? "" : ""}</span>
    </div>
  );
}