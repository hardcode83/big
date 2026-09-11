"use client";

import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

import type { Review, ReviewDraft } from "../data";

/**
 * Modal that confirms **Marcar como publicada** from the review detail (D12,
 * R4.1, R4.2, R4.3).
 *
 * The wording is "**already** posted on the corresponding channel", not
 * "publish": the system does not publish anything — the operator does, on
 * the OTA, and the dialog only records that fact. R4.1 is explicit about
 * that.
 *
 * The preview shows both `content` (the guest's prose) and the approved
 * `draft_content` (the response that was approved). The body fields are
 * rendered as text, never as HTML — `content` is regla-11 excepción 4
 * (third-party prose), `draft_content` is regla-11 closed-vocabulary; both
 * survive verbatim, recombined by nothing (D11).
 *
 * Closing the dialog without confirmation does **not** fire the mutation
 * (R4.2): the row stays as `APPROVED` and the operator can come back to it.
 *
 * The mutation fires only with `action: "MARK_POSTED"` (D8, R4.3); no
 * `draft_content` is sent, since marking is independent of the response text.
 */
export interface MarkPostedDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  review: Review;
  draft: ReviewDraft | null;
  /** When true, the dialog's confirm button is disabled (D9, global isBusy). */
  isBusy: boolean;
  onConfirm: () => void;
}

export function MarkPostedDialog({
  open,
  onOpenChange,
  review,
  draft,
  isBusy,
  onConfirm,
}: MarkPostedDialogProps) {
  const { t } = useTranslation("reviews");

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("markPosted.dialog.title")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("markPosted.dialog.body")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-3 border-t border-border pt-3">
          <div className="flex flex-col gap-1">
            <span className="text-body-sm font-medium text-muted-foreground">
              {t("preview.guestContent")}
            </span>
            <p className="whitespace-pre-wrap text-body-base text-foreground">
              {review.content ?? t("preview.empty")}
            </p>
          </div>
          {draft !== null && (
            <div className="flex flex-col gap-1">
              <span className="text-body-sm font-medium text-muted-foreground">
                {t("preview.draftContent")}
              </span>
              <p className="whitespace-pre-wrap text-body-base text-foreground">
                {draft.draftContent}
              </p>
            </div>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isBusy}>
            {t("markPosted.dialog.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction disabled={isBusy} onClick={onConfirm}>
            {t("markPosted.dialog.confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}