"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { PropertyDashboardCard } from "../data";
import { formatDate, formatDateTime } from "../lib/format";
import { stateColorGroup, type StateColorGroup } from "../lib/state-color";

/**
 * Presentational property card (PRD §9.1). It renders exactly what the DTO
 * carries — no business logic, no state computation. The operational state's
 * color comes from `stateColorGroup`; its label and all chrome come from the
 * `dashboard` i18n namespace.
 */
const STATE_BADGE_CLASS: Record<StateColorGroup, string> = {
  green:
    "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-800",
  blue: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:border-blue-800",
  amber:
    "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800",
  red: "bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-200 dark:border-red-800",
  gray: "bg-muted text-muted-foreground border-border",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

export function PropertyCard({ card }: { card: PropertyDashboardCard }) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const reservation = card.currentOrNextReservation;

  return (
    <article className="flex flex-col gap-3 rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h3 className="truncate text-base font-semibold text-foreground">
          {card.propertyCode}
        </h3>
        <Badge
          variant="outline"
          className={cn(STATE_BADGE_CLASS[stateColorGroup(card.operationalState)])}
        >
          {t(`state.${card.operationalState}`)}
        </Badge>
      </div>

      <div className="flex flex-col gap-1.5">
        <Field label={t("card.reservation")}>
          {reservation?.reference ?? t("card.noReservation")}
        </Field>
        <Field label={t("card.guest")}>
          {reservation?.guestName ?? t("card.noGuest")}
        </Field>
        {reservation ? (
          <>
            <Field label={t("card.checkIn")}>
              {formatDate(reservation.checkIn, locale)}
            </Field>
            <Field label={t("card.checkOut")}>
              {formatDate(reservation.checkOut, locale)}
            </Field>
          </>
        ) : null}
        <Field label={t("card.cleaning")}>
          {card.cleaningStatus ?? t("card.noCleaning")}
        </Field>
        <Field label={t("card.openIncidents")}>{card.openIncidentsCount}</Field>
        {card.nextAction ? (
          <Field label={t("card.nextAction")}>
            {card.nextAction.label}
            {card.nextAction.responsible
              ? ` · ${t("card.responsible")}: ${card.nextAction.responsible}`
              : null}
          </Field>
        ) : null}
        {card.lastEventLabel && card.lastEventAt ? (
          <Field label={t("card.lastEvent")}>
            {card.lastEventLabel} · {formatDateTime(card.lastEventAt, locale)}
          </Field>
        ) : null}
      </div>

      <Link
        href={`/properties/${card.propertyId}`}
        className="mt-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
      >
        {t("card.openDetail")}
      </Link>
    </article>
  );
}
