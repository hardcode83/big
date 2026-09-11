"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { ReviewAction, ReviewStatus } from "../data";
import { legalActions } from "../lib/review-actions";
import type { ReviewerRole } from "../lib/review-actions";

/**
 * The decision / edit buttons for one row (design D5, R3.1, R3.2, R3.3).
 *
 * Confirmation is **in two steps inside the row**, the same shape as
 * `pricing-web/components/decision-controls.tsx` — no `AlertDialog` here
 * because the operator is already looking at the row's `draft_content` on
 * the open detail, and the dialog would be a second surface for the same
 * content (D12, R4.2 reserved the dialog for **Marcar como publicada**
 * specifically).
 *
 * **`legalActions(status, role)`** decides which buttons appear. This is
 * affordance, not authority: the backend validates and answers `409` (R3.5).
 *
 * **EDIT after APPROVED is omitted** (R3.3 / entities.py:369): the draft is
 * locked once `approved_at` is set.
 *
 * `MARK_POSTED` does **not** appear in the row's action bar (D5, R4.2): it
 * lives in the detail's `AlertDialog` because the operator needs the preview
 * of the `content` and the approved `draft_content` to confirm before the
 * row goes to a terminal state (no undo).
 */
export interface ReviewActionsProps {
  reviewId: string;
  status: ReviewStatus;
  role: ReviewerRole;
  /** The detail mutation's pending state for this row. */
  isPending: boolean;
  /** Any review mutation is in flight — global disable (D9). */
  isBusy: boolean;
  onConfirm: (input: {
    reviewId: string;
    action: Exclude<ReviewAction, "MARK_POSTED">;
  }) => void;
}

/** The i18n key of each move's button label. */
const LABEL_KEY: Record<
  Exclude<ReviewAction, "MARK_POSTED">,
  string
> = {
  APPROVE: "respond.approve",
  IGNORE: "respond.ignore",
  EDIT: "respond.edit",
};

export function ReviewActions({
  reviewId,
  status,
  role,
  isPending,
  isBusy,
  onConfirm,
}: ReviewActionsProps) {
  const { t } = useTranslation("reviews");
  const moves = legalActions(status, role).filter(
    (a): a is Exclude<ReviewAction, "MARK_POSTED"> => a !== "MARK_POSTED",
  );

  /** Local to this row: two two can never be mid-confirmation of each other. */
  const [pendingAction, setPendingAction] =
    useState<Exclude<ReviewAction, "MARK_POSTED"> | null>(null);

  if (moves.length === 0) {
    return null;
  }

  if (isPending) {
    return (
      <p className="text-body-sm text-muted-foreground">{t("respond.sending")}</p>
    );
  }

  if (pendingAction !== null) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-body-sm text-foreground">
          {t(`respond.confirmQuestion.${pendingAction}`)}
        </span>
        <Button
          type="button"
          variant="outline"
          disabled={isBusy}
          onClick={() => {
            // The confirmation is what fires the mutation (R3.3).
            onConfirm({ reviewId, action: pendingAction });
            setPendingAction(null);
          }}
        >
          {t("respond.confirm")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => setPendingAction(null)}
        >
          {t("respond.cancel")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {moves.map((action) => (
        <Button
          key={action}
          type="button"
          variant="outline"
          disabled={isBusy}
          onClick={() => setPendingAction(action)}
        >
          {t(LABEL_KEY[action])}
        </Button>
      ))}
    </div>
  );
}