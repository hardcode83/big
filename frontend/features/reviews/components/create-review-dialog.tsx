"use client";

import { useState } from "react";
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
import { Button } from "@/components/ui/button";

import type {
  CreateReviewInput,
  PropertySummary,
  ReviewChannel,
} from "../data";

/**
 * The five values of `ReviewChannel` are the only ones the backend accepts
 * (`openapi.d.ts:4462`), and the dialog exposes all of them — closing the
 * enum to a subset is what R5.3 forbids.
 */
const CHANNELS: readonly ReviewChannel[] = [
  "AIRBNB",
  "BOOKING",
  "GOOGLE",
  "MANUAL",
  "OTHER",
] as const;

const REVIEWER_NAME_MAX = 200;
const CONTENT_MAX = 4000;
const RATING_MIN = 1;
const RATING_MAX = 5;
const RATING_STEP = 0.5;

/**
 * Modal that creates a review by hand (D12, R5.3, R5.4, R5.5).
 *
 * The form mirrors the backend's `CreateReviewRequest` constraints:
 *
 *  - `property_id` and `channel` are required, the rest is optional;
 *  - `reviewer_name` ≤ 200 chars, `content` ≤ 4000 chars;
 *  - `rating` is a fixed list `1.0..5.0` with step `0.5`, **a number on the
 *    wire** (the contract accepts `number | string | null` and the UI sends
 *    the cleanest form);
 *  - `language` is optional; the backend infers from `content` if absent
 *    (`revenue-reviews.md` R5.1) and the UI does **not** add a constraint
 *    that the backend does not impose (R5.3).
 *
 * **No validation that the backend does not run** (R5.3): the project norm
 * forbids painting the body of a `422`, so any client-side rule that
 * diverges from the server is invisible error UX.
 *
 * The submit button is disabled while the mutation is in flight (D9); the
 * cancel button stays enabled so the operator can abandon without waiting.
 *
 * Closing without sending does **not** fire the mutation: the dialog
 * resets its local state on close via `key={open ? "open" : "closed"}`
 * (the same pattern as `resolve-incident-dialog.tsx` in the dashboard).
 *
 * **`errorKey` renders INSIDE the dialog, not just in the view's shared
 * banner** (R5.5): `AlertDialogContent` is a portal overlay
 * (`fixed inset-0 z-50`) that covers the whole screen, so a `422` shown only
 * in `reviews-view.tsx`'s `role="status"` region would sit behind this
 * dialog and never be seen while the form is still open — exactly the case
 * a create failure needs.
 */
export interface CreateReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: readonly PropertySummary[];
  isBusy: boolean;
  /** Localized error key from `createErrorKey`, or `null` when there is none to show. */
  errorKey: string | null;
  onSubmit: (input: CreateReviewInput) => void;
}

export function CreateReviewDialog({
  open,
  onOpenChange,
  catalog,
  isBusy,
  errorKey,
  onSubmit,
}: CreateReviewDialogProps) {
  const { t } = useTranslation("reviews");
  const [propertyId, setPropertyId] = useState("");
  const [channel, setChannel] = useState<ReviewChannel>("AIRBNB");
  const [reviewerName, setReviewerName] = useState("");
  const [rating, setRating] = useState<number>(5);
  const [content, setContent] = useState("");

  const canSubmit = propertyId !== "" && !isBusy;

  function reset() {
    setPropertyId("");
    setChannel("AIRBNB");
    setReviewerName("");
    setRating(5);
    setContent("");
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("create.title")}</AlertDialogTitle>
          <AlertDialogDescription>{t("create.body")}</AlertDialogDescription>
        </AlertDialogHeader>
        <form
          key={open ? "open" : "closed"}
          className="flex flex-col gap-3 border-t border-border pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            onSubmit({
              propertyId,
              channel,
              ...(reviewerName !== "" ? { reviewerName } : {}),
              rating,
              ...(content !== "" ? { content } : {}),
            });
          }}
        >
          <label className="flex flex-col gap-1 text-body-base">
            <span className="font-medium text-foreground">
              {t("create.fields.property")}
            </span>
            <select
              value={propertyId}
              onChange={(e) => setPropertyId(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
              required
            >
              <option value="">{t("create.selectProperty")}</option>
              {catalog.map((property) => (
                <option key={property.id} value={property.id}>
                  {property.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-body-base">
            <span className="font-medium text-foreground">
              {t("create.fields.channel")}
            </span>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value as ReviewChannel)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {t(`channel.${c}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-body-base">
            <span className="font-medium text-foreground">
              {t("create.fields.reviewerName")}
            </span>
            <input
              type="text"
              value={reviewerName}
              maxLength={REVIEWER_NAME_MAX}
              onChange={(e) => setReviewerName(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
            />
          </label>
          <label className="flex flex-col gap-1 text-body-base">
            <span className="font-medium text-foreground">
              {t("create.fields.rating")}
            </span>
            <select
              value={rating}
              onChange={(e) => setRating(Number(e.target.value))}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
            >
              {Array.from(
                { length: (RATING_MAX - RATING_MIN) / RATING_STEP + 1 },
                (_, i) => RATING_MIN + i * RATING_STEP,
              ).map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-body-base">
            <span className="font-medium text-foreground">
              {t("create.fields.content")}
            </span>
            <textarea
              value={content}
              maxLength={CONTENT_MAX}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
            />
          </label>
          {errorKey !== null && (
            <p
              role="status"
              aria-live="polite"
              className="rounded-md border border-destructive bg-destructive/10 px-3 py-2 text-body-base text-destructive"
            >
              {t(errorKey)}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel type="button" disabled={isBusy}>
              {t("create.cancel")}
            </AlertDialogCancel>
            <Button type="submit" disabled={!canSubmit}>
              {t("create.submit")}
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}