"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { PropertyStateBadge } from "@/components/property-state-badge";
import { cn } from "@/lib/utils";

import {
  BlockedTransitionsSection,
  type BlockedTransitionSummary,
} from "../stalls";

import type { PropertyDashboardCard } from "../data";
import { formatDate, formatDateTime } from "../lib/format";

/**
 * Presentational property card (PRD §9.1). It renders exactly what the DTO
 * carries — no business logic, no state computation. The operational state's
 * color comes from the shared `PropertyStateBadge`, which owns the only copy of
 * the PRD §9.1 color table since `properties-web` needed the same badge (design
 * D2); its label and all chrome come from the `dashboard` i18n namespace.
 *
 * The blocked-transitions section is mounted **after** the incident count and
 * **before** the next action — `dashboard-web-frontend.md` §9.1 reserves the
 * slot. The card renders unchanged when `stalls` is undefined or empty
 * (proposal `blocked-transitions-web` R1.3).
 */

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid min-w-0 grid-cols-[minmax(0,auto)_minmax(0,1fr)] items-baseline gap-x-3 text-sm",
        className,
      )}
    >
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-right font-medium text-foreground">
        {children}
      </span>
    </div>
  );
}

export function PropertyCard({
  card,
  stalls,
}: {
  card: PropertyDashboardCard;
  stalls?: BlockedTransitionSummary[];
}) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const reservation = card.currentOrNextReservation;
  const headingId = `property-card-${card.propertyId}`;
  const incidentsHeadingId = `${headingId}-incidents`;
  const stallsHeadingId = `${headingId}-stalls`;
  const actionHeadingId = `${headingId}-action`;
  const lastEventHeadingId = `${headingId}-last-event`;

  return (
    <article
      aria-labelledby={headingId}
      className="flex h-full min-w-0 flex-col gap-4 rounded-lg border bg-card p-4 shadow-sm"
    >
      <header className="flex items-start justify-between gap-3">
        <h3
          id={headingId}
          className="min-w-0 flex-1 break-words text-base font-semibold text-foreground"
        >
          {card.propertyCode}
        </h3>
        <PropertyStateBadge
          state={card.operationalState}
          label={t(`state.${card.operationalState}`)}
        />
      </header>

      <div className="flex min-w-0 flex-col gap-3">
        <section
          aria-labelledby={incidentsHeadingId}
          className="flex items-center justify-between gap-3 rounded-md border bg-muted p-3"
        >
          <h4 id={incidentsHeadingId} className="text-sm font-semibold text-foreground">
            {t("card.openIncidents")}
          </h4>
          <span className="text-lg font-semibold text-foreground">
            {card.openIncidentsCount}
          </span>
        </section>

        {stalls && stalls.length > 0 ? (
          <BlockedTransitionsSection
            stalls={stalls}
            headingId={stallsHeadingId}
          />
        ) : null}

        {card.nextAction ? (
          <section
            aria-labelledby={actionHeadingId}
            className="rounded-md border border-primary p-3"
          >
            <h4 id={actionHeadingId} className="text-sm font-semibold text-foreground">
              {t("card.nextAction")}
            </h4>
            <p className="mt-1 break-words text-sm font-semibold text-foreground">
              {card.nextAction.label}
            </p>
            {card.nextAction.responsible ? (
              <p className="mt-1 break-words text-sm text-muted-foreground">
                {t("card.responsible")}: {card.nextAction.responsible}
              </p>
            ) : null}
          </section>
        ) : null}

        <section aria-label={t("card.reservation")} className="min-w-0">
          <div className="mt-2 grid min-w-0 gap-1.5 sm:grid-cols-2">
            <Field label={t("card.reservation")} className="sm:col-span-2">
              {reservation?.reference ?? t("card.noReservation")}
            </Field>
            <Field label={t("card.guest")} className="sm:col-span-2">
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
          </div>
        </section>

        <section aria-label={t("card.cleaning")} className="min-w-0">
          <div className="mt-2">
            <Field label={t("card.cleaning")}>
              {card.cleaningStatus ?? t("card.noCleaning")}
            </Field>
          </div>
        </section>

        {card.lastEventLabel && card.lastEventAt ? (
          <section aria-labelledby={lastEventHeadingId} className="min-w-0">
            <h4 id={lastEventHeadingId} className="text-sm font-semibold text-foreground">
              {t("card.lastEvent")}
            </h4>
            <p className="mt-2 break-words text-sm text-muted-foreground">
              {card.lastEventLabel} · {formatDateTime(card.lastEventAt, locale)}
            </p>
          </section>
        ) : null}
      </div>

      <Link
        href={`/properties/${card.propertyId}`}
        className="tap-target mt-auto inline-flex items-center text-sm font-medium text-primary underline-offset-4 hover:underline"
      >
        {t("card.openDetail")}
      </Link>
    </article>
  );
}
