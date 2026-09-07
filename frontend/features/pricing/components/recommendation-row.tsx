"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import { cn } from "@/lib/utils";

import type {
  DecisionStatus,
  PriceRecommendation,
  PropertySummary,
} from "../data";
import { fmtDay, fmtDecimal } from "../lib/format";
import type { PropertyDirectory } from "../lib/property-directory";
import { resolvePropertyIdentity } from "../lib/property-directory";
import { recommendationStatusTone } from "../lib/recommendation-status";
import { DecisionControls } from "./decision-controls";

/**
 * One recommendation, as a card rather than a table row — the screen is
 * mobile-first and a table of five columns cannot avoid horizontal scroll at
 * 320 px. Each field carries its own label, so the column names still name the
 * data at every width.
 *
 * What is **not** here is as deliberate as what is: no `current_price`, no
 * `confidence`, no timestamp (R2.5, R2.6). None of the three crosses the
 * boundary at all (design D3), so this is not discipline — the data does not
 * exist in this layer.
 *
 * The `explanation` is rendered as a **text child** and never as markup (R2.7,
 * design D16). React escapes by default, so the requirement reduces to a
 * prohibition — no `dangerouslySetInnerHTML` anywhere in this feature — and to
 * the test that proves a marked-up explanation renders literally. It is a
 * free-text sink under rule 11 of `steering/security.md` for one concrete
 * reason: the `name` a manager typed into a season or an event is the only part
 * of the sentence the backend's template does not compose.
 *
 * It goes folded into a `<details>` (design D23): the canonical sentence runs to
 * four lines, and the queue has to be readable top to bottom. The browser gives
 * keyboard, `aria-expanded` and the expand/collapse announcement for free.
 */
export interface RecommendationRowProps {
  recommendation: PriceRecommendation;
  properties: PropertyDirectory<PropertySummary>;
  decision: {
    isPending: boolean;
    isBusy: boolean;
    onConfirm: (input: {
      recommendationId: string;
      status: DecisionStatus;
    }) => void;
  };
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5 text-body-base", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-body-medium text-foreground">
        {children}
      </span>
    </div>
  );
}

export function RecommendationRow({
  recommendation,
  properties,
  decision,
}: RecommendationRowProps) {
  const { t, i18n } = useTranslation("pricing");
  const locale = i18n.language;
  const headingId = `pricing-recommendation-${recommendation.id}`;
  const property = resolvePropertyIdentity(recommendation.propertyId, properties);

  return (
    <li aria-labelledby={headingId} className="min-w-0 list-none">
      <Card className="flex min-w-0 flex-col gap-3 p-4">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <h3
          id={headingId}
          className="min-w-0 flex-1 break-words text-body-lg font-semibold text-foreground"
        >
          <span className="sr-only">
            {t("recommendations.columns.property")}:{" "}
          </span>
          {/* The three degraded shapes of R2.8; the raw id is never shown. */}
          {property.kind === "resolved" ? (
            `${property.value.internalCode} ${t("separator")} ${property.value.name}`
          ) : property.kind === "pending" ? (
            <>
              <span aria-hidden="true" className="text-muted-foreground">
                —
              </span>
              <span className="sr-only">{t("identity.loading")}</span>
            </>
          ) : property.kind === "portfolio" ? (
            <span className="text-muted-foreground">
              {t("identity.portfolio")}
            </span>
          ) : (
            <span className="italic text-muted-foreground">
              {t("identity.unavailable")}
            </span>
          )}
        </h3>
        <Badge
          variant="outline"
          className={cn(
            TONE_BADGE_CLASS[recommendationStatusTone(recommendation.status)],
          )}
        >
          <span className="sr-only">
            {t("recommendations.columns.status")}:{" "}
          </span>
          {t(`status.${recommendation.status}`)}
        </Badge>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("recommendations.columns.date")}>
          {fmtDay(recommendation.date, locale)}
        </Field>
        <Field label={t("recommendations.columns.recommendedPrice")}>
          {fmtDecimal(recommendation.recommendedPrice, locale)}
        </Field>
      </div>

      <details className="min-w-0">
        <summary className="tap-target cursor-pointer text-body-base text-muted-foreground">
          {t("recommendations.columns.explanation")}
        </summary>
        {/*
          Text child, never markup (R2.7, D16). The sentence arrives in English
          from a closed backend template and is neither translated nor parsed.
        */}
        <p className="mt-2 min-w-0 break-words text-body-base text-foreground">
          {recommendation.explanation}
        </p>
      </details>

      <DecisionControls
        recommendationId={recommendation.id}
        status={recommendation.status}
        isPending={decision.isPending}
        isBusy={decision.isBusy}
        onConfirm={decision.onConfirm}
      />
      </Card>
    </li>
  );
}
