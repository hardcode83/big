"use client";

import { useTranslation } from "react-i18next";

import type {
  PropertySummary,
  ReviewChannel,
  ReviewSentiment,
  ReviewStatus,
} from "../data";

const CHANNELS: readonly ReviewChannel[] = [
  "AIRBNB",
  "BOOKING",
  "GOOGLE",
  "MANUAL",
  "OTHER",
] as const;

const SENTIMENTS: readonly ReviewSentiment[] = [
  "POSITIVE",
  "NEUTRAL",
  "NEGATIVE",
] as const;

const STATUSES: readonly ReviewStatus[] = [
  "NEW",
  "DRAFTED",
  "APPROVED",
  "POSTED_MANUALLY",
  "IGNORED",
] as const;

/**
 * The filter row shared by both tabs (design D14/D7, R2.1, R5.1): property,
 * channel, sentiment, rating range and date range are common to Borradores
 * and Reseñas — only `status` differs, and it renders only when the caller
 * passes `onStatusChange` (Reseñas). Borradores has no status selector: its
 * filter is fixed to `DRAFTED` (R2.1), not a choice.
 *
 * Presentational only, the same posture as `reviews-pagination.tsx` (D16):
 * it owns no store access, because the two tabs write to two independent
 * slices (`drafts`/`reviews`, D14) and this component has no way to tell
 * which one it is rendered for except through its props.
 */
export interface ReviewFiltersProps {
  catalog: readonly PropertySummary[];
  propertyId?: string;
  onPropertyIdChange: (value?: string) => void;
  channel?: ReviewChannel;
  onChannelChange: (value?: ReviewChannel) => void;
  sentiment?: ReviewSentiment | null;
  onSentimentChange: (value?: ReviewSentiment | null) => void;
  ratingMin?: string;
  onRatingMinChange: (value?: string) => void;
  ratingMax?: string;
  onRatingMaxChange: (value?: string) => void;
  dateFrom?: string;
  onDateFromChange: (value?: string) => void;
  dateTo?: string;
  onDateToChange: (value?: string) => void;
  /** Only the Reseñas tab passes this (R5.1); Borradores stays fixed to DRAFTED. */
  status?: ReviewStatus;
  onStatusChange?: (value?: ReviewStatus) => void;
}

export function ReviewFilters({
  catalog,
  propertyId,
  onPropertyIdChange,
  channel,
  onChannelChange,
  sentiment,
  onSentimentChange,
  ratingMin,
  onRatingMinChange,
  ratingMax,
  onRatingMaxChange,
  dateFrom,
  onDateFromChange,
  dateTo,
  onDateToChange,
  status,
  onStatusChange,
}: ReviewFiltersProps) {
  const { t } = useTranslation("reviews");

  return (
    <div className="flex flex-wrap gap-3">
      <label className="flex flex-col gap-1 text-body-base">
        <span className="font-medium text-foreground">
          {t("filters.property.label")}
        </span>
        <select
          value={propertyId ?? ""}
          onChange={(e) =>
            onPropertyIdChange(e.target.value === "" ? undefined : e.target.value)
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
          value={channel ?? ""}
          onChange={(e) =>
            onChannelChange(
              e.target.value === "" ? undefined : (e.target.value as ReviewChannel),
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
          {t("filters.sentiment.label")}
        </span>
        <select
          value={sentiment ?? ""}
          onChange={(e) =>
            onSentimentChange(
              e.target.value === "" ? undefined : (e.target.value as ReviewSentiment),
            )
          }
          className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
        >
          <option value="">{t("filters.sentiment.all")}</option>
          {SENTIMENTS.map((s) => (
            <option key={s} value={s}>
              {t(`sentiment.${s}`)}
            </option>
          ))}
        </select>
      </label>
      {onStatusChange && (
        <label className="flex flex-col gap-1 text-body-base">
          <span className="font-medium text-foreground">
            {t("filters.status.label")}
          </span>
          <select
            value={status ?? ""}
            onChange={(e) =>
              onStatusChange(
                e.target.value === "" ? undefined : (e.target.value as ReviewStatus),
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
      )}
      <label className="flex flex-col gap-1 text-body-base">
        <span className="font-medium text-foreground">
          {t("filters.rating.label")}
        </span>
        <span className="flex items-center gap-2">
          <input
            type="number"
            min={1}
            max={5}
            step={0.5}
            aria-label={t("filters.rating.min")}
            placeholder={t("filters.rating.min")}
            value={ratingMin ?? ""}
            onChange={(e) =>
              onRatingMinChange(e.target.value === "" ? undefined : e.target.value)
            }
            className="w-20 rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
          />
          <input
            type="number"
            min={1}
            max={5}
            step={0.5}
            aria-label={t("filters.rating.max")}
            placeholder={t("filters.rating.max")}
            value={ratingMax ?? ""}
            onChange={(e) =>
              onRatingMaxChange(e.target.value === "" ? undefined : e.target.value)
            }
            className="w-20 rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
          />
        </span>
      </label>
      <label className="flex flex-col gap-1 text-body-base">
        <span className="font-medium text-foreground">
          {t("filters.dateFrom.label")}
        </span>
        <input
          type="date"
          value={dateFrom ?? ""}
          onChange={(e) =>
            onDateFromChange(e.target.value === "" ? undefined : e.target.value)
          }
          className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
        />
      </label>
      <label className="flex flex-col gap-1 text-body-base">
        <span className="font-medium text-foreground">
          {t("filters.dateTo.label")}
        </span>
        <input
          type="date"
          value={dateTo ?? ""}
          onChange={(e) =>
            onDateToChange(e.target.value === "" ? undefined : e.target.value)
          }
          className="rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
        />
      </label>
    </div>
  );
}
