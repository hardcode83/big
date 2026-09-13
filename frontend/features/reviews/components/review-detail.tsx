"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type {
  Review,
  ReviewDraft,
} from "../data";
import { fmtDay, fmtRating } from "../lib/format";
import { legalActions } from "../lib/review-actions";
import type { ReviewerRole } from "../lib/review-actions";
import { MarkPostedDialog } from "./mark-posted-dialog";

/**
 * Detail for one review, mounted above the listing on click (R6.1, R6.2,
 * R6.3, R6.4).
 *
 * **No new route**: the listing stays in place and the detail is an overlay
 * over the row the operator opened. Closing it returns focus to the row.
 *
 * **The draft mounts only when the detail's status is `DRAFTED`** (R6.1).
 * `IGNORED` reviews answer `404` from `GET /reviews/{id}/response`
 * (R5.4 del spec backend) and the detail renders without a draft card.
 *
 * **`content` and `draft_content` are rendered as text, never as HTML**
 * (R6.2, D11). They are regla-11 sinks (excepción 4 the first, closed
 * vocabulary the second) and the UI recombines nothing.
 *
 * **The Mark Posted dialog** wraps the dialog so the operator sees the
 * preview of the prose before confirming (D12, R4.1, R4.2, R4.3).
 *
 * **Edit** is in-line: the operator changes `draft_content` and submits
 * with `action: "EDIT"`. The validation is `draftContent.trim().length > 0`,
 * in line with the no-empty-content norm of every mutation in the tree.
 *
 * **`onConfirm` only ever fires with `action: "EDIT"` from this component.**
 * Approve/Ignore are the row's `ReviewActions`' job (rendered by
 * `drafts-panel.tsx`/`reviews-panel.tsx`, which stays mounted under this
 * detail overlay) — narrowing the type here is what stops a future edit from
 * re-adding the duplicate buttons this file used to render.
 *
 * **`role` gates both Edit and Mark-Posted through the same `legalActions`
 * matrix the row uses** (D5, D15): opening a review's detail is not itself
 * gated by role — any authenticated visitor to `/reviews` can open any row —
 * so without this check a `PROPERTY_MANAGER` who opens an `APPROVED` review
 * would see **Marcar como publicada**, an owner-only action per `policy.py`'s
 * `_REVIEW_OPERATE`/`_REVIEW_MANAGE` split and D15's UX framing. The backend
 * still decides (R7.4) — this is the UI's mirror of that split, not a second
 * authority.
 */
export interface ReviewDetailProps {
  review: Review;
  draft: ReviewDraft | null;
  /** Global disable (D9): every mutation in flight disables this row's controls. */
  isBusy: boolean;
  /** The currently in-flight mutation is this row's (D9). */
  isPending: boolean;
  /** The current user's role for the action matrix (D5, D15). */
  role: ReviewerRole;
  onClose: () => void;
  onConfirm: (input: {
    reviewId: string;
    action: "EDIT";
    draftContent: string;
  }) => void;
  onMarkPosted: (reviewId: string) => void;
}

export function ReviewDetail({
  review,
  draft,
  isBusy,
  isPending,
  role,
  onClose,
  onConfirm,
  onMarkPosted,
}: ReviewDetailProps) {
  const { t, i18n } = useTranslation("reviews");
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(draft?.draftContent ?? "");
  const [markOpen, setMarkOpen] = useState(false);
  const moves = legalActions(review.status, role);
  const canEdit = moves.includes("EDIT");
  const canMarkPosted = moves.includes("MARK_POSTED");

  function startEdit() {
    setEditValue(draft?.draftContent ?? "");
    setEditing(true);
  }

  function submitEdit() {
    const trimmed = editValue.trim();
    if (trimmed.length === 0) return;
    onConfirm({
      reviewId: review.id,
      action: "EDIT",
      draftContent: trimmed,
    });
    setEditing(false);
  }

  return (
    <div
      className="flex flex-col gap-4 rounded-md border border-border bg-background p-4"
      data-testid="review-detail"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-headline-md font-semibold text-foreground">
          {t("detail.title")}
        </h3>
        <Button type="button" variant="ghost" onClick={onClose}>
          {t("detail.close")}
        </Button>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-body-base font-medium text-muted-foreground">
          {t("preview.guestText")}
        </span>
        <p className="whitespace-pre-wrap text-body-base text-foreground">
          {review.content ?? t("preview.empty")}
        </p>
      </div>
      {review.rating !== null && (
        <p className="text-body-base text-foreground">
          {t("preview.rating")}
          {": "}
          {fmtRating(review.rating, i18n.language)}/5
        </p>
      )}
      <p className="text-body-base text-muted-foreground">
        {t(`channel.${review.channel}`)}
        {review.publishedAt !== null
          ? ` · ${fmtDay(review.publishedAt, i18n.language)}`
          : ""}
      </p>
      {review.reviewerName !== null && (
        <p className="text-body-base text-muted-foreground">
          {t("preview.reviewerName")}
          {": "}
          {review.reviewerName}
        </p>
      )}
      {review.sentiment !== null && (
        <p className="text-body-base text-muted-foreground">
          {t("preview.sentiment")}
          {": "}
          {t(`sentiment.${review.sentiment}`)}
        </p>
      )}
      {review.aiSummary !== null && (
        <div className="flex flex-col gap-1">
          <span className="text-body-base font-medium text-muted-foreground">
            {t("preview.aiSummary")}
          </span>
          <p className="whitespace-pre-wrap text-body-base text-foreground">
            {review.aiSummary}
          </p>
        </div>
      )}
      {review.recurringIssues.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {review.recurringIssues.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-muted px-2 py-0.5 text-body-base text-foreground"
            >
              {t(`recurringIssue.${tag}`)}
            </span>
          ))}
        </div>
      )}
      {draft !== null && (
        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <span className="text-body-base font-medium text-muted-foreground">
            {t("preview.draftContent")}
          </span>
          {editing ? (
            <>
              <textarea
                value={editValue}
                onChange={(event) => setEditValue(event.target.value)}
                rows={4}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
              />
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={isBusy || editValue.trim().length === 0}
                  onClick={submitEdit}
                >
                  {t("respond.editSave")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setEditing(false)}
                >
                  {t("respond.editCancel")}
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="whitespace-pre-wrap text-body-base text-foreground">
                {draft.draftContent}
              </p>
              {canEdit && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={isBusy}
                  onClick={startEdit}
                >
                  {t("respond.editDraft")}
                </Button>
              )}
            </>
          )}
        </div>
      )}
      {isPending && (
        <p className="text-body-base text-muted-foreground">{t("respond.sending")}</p>
      )}
      {/*
       * Approve/Ignore are NOT rendered here (design D5, D12): they live in the
       * row's `ReviewActions` (rendered by `drafts-panel.tsx`/`reviews-panel.tsx`),
       * which stays mounted under this detail overlay. Rendering them here too
       * would double the controls for the same review — the exact bug the
       * round-1 review-panel fix was supposed to close and initially missed
       * (only the i18n keys were touched, not this block). `Marcar como
       * publicada` is the one exception: it opens THIS detail's dialog, because
       * only the detail has loaded the `content`/`draft_content` the preview
       * needs (R4.2) — the row never fetches them.
       */}
      {canMarkPosted && (
        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <Button
            type="button"
            variant="outline"
            disabled={isBusy}
            onClick={() => setMarkOpen(true)}
          >
            {t("respond.markPosted")}
          </Button>
        </div>
      )}
      <MarkPostedDialog
        open={markOpen}
        onOpenChange={setMarkOpen}
        review={review}
        draft={draft}
        isBusy={isBusy}
        onConfirm={() => {
          setMarkOpen(false);
          onMarkPosted(review.id);
        }}
      />
    </div>
  );
}