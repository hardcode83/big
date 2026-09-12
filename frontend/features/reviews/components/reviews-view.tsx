"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth, useHasPermission } from "@/lib/auth";

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
} from "../hooks/use-reviews-data";
import { createErrorKey, readErrorKey, respondErrorKey } from "../lib/reviews-error";
import { CreateReviewDialog } from "./create-review-dialog";
import { DraftsPanel } from "./drafts-panel";
import { ReviewDetail } from "./review-detail";
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
 *
 * **A single `role="status" aria-live="polite"` error region** (D9, R3.5,
 * R3.7, R5.5) surfaces `respond.error`/`create.error` through
 * `respondErrorKey`/`createErrorKey` — mapping by HTTP status only, never
 * the backend's raw message (R3.6). Without this the mutation still runs
 * and the `onSettled` refetch still happens, but a `409` (someone else
 * already decided the row) or a `422` (invalid create) fails **silently**:
 * the row just resets with no explanation. `respondErrorKey`/`createErrorKey`
 * existed and were unit-tested from the start (`lib/reviews-error.test.ts`)
 * but were never called from a component — QA's final-gate pass caught this
 * before archive.
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
  // Gated through the declared permission mirror (D15, R7.4), not a role
  // literal comparison: the mirror is the single place the UX split between
  // owner-decides / manager-creates is recorded, and a future permission
  // change only has to touch permissions.ts. There is no equivalent
  // `canDecide` gate here: `legalActions(status, role)` already encodes the
  // full per-status/per-role decision matrix (D5) that Approve/Ignore/Edit/
  // MarkPosted need, and gating `role` itself behind a second boolean
  // (`canDecide ? role : "other"`, the shape this replaced) silently
  // collapsed the manager to "other" everywhere — hiding Edit from the
  // manager too, since MANAGE_REVIEW_DECISIONS is owner-only.
  const canCreate = useHasPermission("CREATE_REVIEW_UI");

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

  // Create's error renders inside CreateReviewDialog, not here: that dialog
  // is a full-screen portal overlay and this banner would sit invisibly
  // behind it while the form is still open (see CreateReviewDialogProps.errorKey).
  const respondError = respond.isError ? respondErrorKey(respond.error) : null;

  return (
    <div className="flex flex-col gap-3" data-testid="reviews-view">
      <h1 className="text-headline-lg font-semibold text-foreground">
        {t("title")}
      </h1>
      {respondError !== null && (
        <p
          role="status"
          aria-live="polite"
          className="rounded-md border border-destructive bg-destructive/10 px-3 py-2 text-body-base text-destructive"
        >
          {t(respondError)}
        </p>
      )}
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
                canCreate={canCreate}
                createDialogOpen={createDialogOpen}
                onOpenCreateDialog={() => canCreate && setCreateDialogOpen(true)}
                isMutationPending={isBusy}
                pendingReviewId={
                  respond.isPending && respond.variables && "reviewId" in respond.variables
                    ? respond.variables.reviewId
                    : null
                }
                onOpenRow={openRow}
                role={role}
                onConfirm={respondFromRow}
              />
            ),
          },
          reviews: {
            key: "reviews-panel",
            node: (
              <ReviewsPanel
                catalog={catalogData ?? []}
                catalogPending={catalog.isPending}
                canCreate={canCreate}
                createDialogOpen={createDialogOpen}
                onOpenCreateDialog={() => canCreate && setCreateDialogOpen(true)}
                onOpenRow={openRow}
                role={role}
                isMutationPending={isBusy}
                pendingReviewId={
                  respond.isPending && respond.variables && "reviewId" in respond.variables
                    ? respond.variables.reviewId
                    : null
                }
                onConfirm={respondFromRow}
              />
            ),
          },
        }}
      />
      {detailReviewId !== null && detail.isPending && (
        <p role="status" aria-live="polite" className="text-body-base text-muted-foreground">
          {t("detail.loading")}
        </p>
      )}
      {detailReviewId !== null && detail.isError && (
        <p role="status" aria-live="polite" className="text-body-base text-destructive">
          {t(readErrorKey(detail.error))}
        </p>
      )}
      {detailReviewId !== null && detail.data && (
        <ReviewDetail
          review={detail.data}
          draft={draft.data ?? null}
          isBusy={isBusy}
          isPending={isPendingThisRow(detailReviewId)}
          role={role}
          onClose={closeDetail}
          onConfirm={respondFromRow}
          onMarkPosted={(reviewId) => {
            respond.mutate({ reviewId, action: "MARK_POSTED" });
          }}
        />
      )}
      {canCreate && (
        <CreateReviewDialog
          open={createDialogOpen}
          onOpenChange={setCreateDialogOpen}
          catalog={catalogData ?? []}
          isBusy={isBusy}
          errorKey={create.isError ? createErrorKey(create.error) : null}
          onSubmit={(input: CreateReviewInput) => {
            create.mutate(input, {
              onSuccess: () => setCreateDialogOpen(false),
            });
          }}
        />
      )}
    </div>
  );
}