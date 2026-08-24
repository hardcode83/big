"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import { cn } from "@/lib/utils";

import type { PricingRule, PropertySummary } from "../data";
import { fmtDecimal } from "../lib/format";
import type { PropertyDirectory } from "../lib/property-directory";
import { resolvePropertyIdentity } from "../lib/property-directory";

/**
 * One pricing rule, read-only (R5.2). Same card shape as the recommendation row
 * and for the same mobile-first reason.
 *
 * **The five JSONB columns appear only as counts** (R5.4). They never reach this
 * component: the boundary replaced them with `modifierCounts` (design D3), so
 * painting their interior — which would mean reimplementing the PRD §7.17 schema
 * in the client — is not possible from here rather than merely discouraged.
 *
 * A `propertyId` of `null` means **the whole portfolio** and is rendered as that
 * positive claim (R5.3), never as a property whose name failed to resolve.
 */
export interface RuleRowProps {
  rule: PricingRule;
  properties: PropertyDirectory<PropertySummary>;
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
    <div className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-sm font-medium text-foreground">
        {children}
      </span>
    </div>
  );
}

/** The five counters, in the declaration order of `ModifierCounts`. */
const MODIFIER_KEYS = [
  "weekday",
  "leadTime",
  "occupancy",
  "seasonality",
  "event",
] as const;

export function RuleRow({ rule, properties }: RuleRowProps) {
  const { t, i18n } = useTranslation("pricing");
  const locale = i18n.language;
  const headingId = `pricing-rule-${rule.id}`;
  const scope = resolvePropertyIdentity(rule.propertyId, properties);

  return (
    <li
      aria-labelledby={headingId}
      className="flex min-w-0 flex-col gap-3 rounded-lg border bg-card p-4 shadow-sm"
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <h3
          id={headingId}
          className="min-w-0 flex-1 break-words text-sm font-semibold text-foreground"
        >
          <span className="sr-only">{t("rules.columns.name")}: </span>
          {rule.name}
        </h3>
        <Badge
          variant="outline"
          className={cn(TONE_BADGE_CLASS[rule.active ? "green" : "gray"])}
        >
          <span className="sr-only">{t("rules.columns.active")}: </span>
          {t(rule.active ? "rules.active.true" : "rules.active.false")}
        </Badge>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("rules.columns.scope")} className="sm:col-span-2">
          {/*
            `null` is «whole portfolio», an affirmation — not an unresolved name
            (R5.3). Only rules can reach this branch.
          */}
          {scope.kind === "portfolio" ? (
            t("rules.scope.portfolio")
          ) : scope.kind === "resolved" ? (
            `${scope.value.internalCode} ${t("separator")} ${scope.value.name}`
          ) : scope.kind === "pending" ? (
            <>
              <span aria-hidden="true" className="text-muted-foreground">
                —
              </span>
              <span className="sr-only">{t("identity.loading")}</span>
            </>
          ) : (
            <span className="italic text-muted-foreground">
              {t("identity.unavailable")}
            </span>
          )}
        </Field>

        <Field label={t("rules.columns.minPrice")}>
          {fmtDecimal(rule.minPrice, locale)}
        </Field>
        <Field label={t("rules.columns.basePrice")}>
          {fmtDecimal(rule.basePrice, locale)}
        </Field>
        <Field label={t("rules.columns.maxPrice")}>
          {fmtDecimal(rule.maxPrice, locale)}
        </Field>
        <Field label={t("rules.columns.maxDailyChangePct")}>
          {/* The `%` lives in the label; the number carries no unit (design D14). */}
          {fmtDecimal(rule.maxDailyChangePct, locale)}
        </Field>

        <Field label={t("rules.columns.modifiers")} className="sm:col-span-2">
          <ul className="flex flex-wrap gap-x-3 gap-y-1">
            {MODIFIER_KEYS.map((key) => (
              <li key={key} className="text-sm font-normal">
                {t(`rules.modifiers.${key}`, {
                  count: rule.modifierCounts[key],
                })}
              </li>
            ))}
          </ul>
        </Field>
      </div>
    </li>
  );
}
