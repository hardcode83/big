"use client";

import { useTranslation } from "react-i18next";

import type { Review } from "../data";
import { fmtDay, fmtRating } from "../lib/format";
import {
  buildPropertyDirectory,
  resolvePropertyIdentity,
} from "../lib/property-directory";
import type { PropertySummary } from "../data";

/**
 * Compact card for one row in either tab (R2.4, R5.2).
 *
 * **`content`, `aiSummary`, `recurringIssues` and the draft are deliberately not
 * here** (design D11, R2.5): they live in the detail, where the row has been
 * opened and the operator is reading, not skimming.
 *
 * **Status badge only on the Reseñas tab** (design D5, R5.2): Borradores is
 * always `DRAFTED` and the badge would be repetition. The `showStatus` prop
 * defaults to `false`, and the drafts panel keeps it that way; the reviews
 * panel passes `true`.
 *
 * **`publishedAt: null` is rendered as an em-dash** localised to `–`, the
 * standard «unknown date» marker (R8.4). The review may exist without a
 * publication date when it was created by hand (R5.4, no OTA round trip).
 *
 * The property catalog is fetched once per page and passed down as a Map
 * (D6). Identity is one of four shapes (`portfolio | pending | unavailable |
 * resolved`); only `pending` and `unavailable` render fallback text, and
 * `pending` is a neutral marker — no «loading…» label that would clutter
 * the queue.
 */
export interface ReviewRowProps {
  review: Review;
  catalog: readonly PropertySummary[];
  catalogPending: boolean;
  /** When `true` (Reseñas tab), paint the localized status badge (R5.2). */
  showStatus: boolean;
  /** Called when the operator clicks anywhere on the row to open the detail. */
  onOpen: (reviewId: string) => void;
}

export function ReviewRow({
  review,
  catalog,
  catalogPending,
  showStatus,
  onOpen,
}: ReviewRowProps) {
  const { t, i18n } = useTranslation("reviews");
  const directory = buildPropertyDirectory(catalog);
  const identity = resolvePropertyIdentity(review.propertyId, {
    index: directory,
    isPending: catalogPending,
  });

  const propertyLabel =
    identity.kind === "resolved"
      ? identity.value.name
      : identity.kind === "pending"
        ? t("identity.pending")
        : t("identity.unavailable");

  return (
    <button
      type="button"
      onClick={() => onOpen(review.id)}
      className="flex w-full flex-col items-start gap-1 border-b border-border py-3 text-left hover:bg-muted/40"
    >
      <div className="flex w-full items-baseline justify-between gap-2">
        <span className="text-body-base font-medium text-foreground">
          {propertyLabel}
        </span>
        <span className="text-body-base text-muted-foreground">
          {t(`channel.${review.channel}`)}
        </span>
      </div>
      <div className="flex w-full items-baseline justify-between gap-2">
        <span className="text-body-base text-muted-foreground">
          {review.rating !== null
            ? `${fmtRating(review.rating, i18n.language)}/5`
            : "–"}
          {" · "}
          {review.sentiment !== null
            ? t(`sentiment.${review.sentiment}`)
            : "–"}
        </span>
        <span className="text-body-base text-muted-foreground">
          {review.publishedAt !== null
            ? fmtDay(review.publishedAt, i18n.language)
            : "–"}
        </span>
      </div>
      {showStatus && (
        <span className="text-body-base font-medium text-foreground">
          {t(`status.${review.status}`)}
        </span>
      )}
    </button>
  );
}