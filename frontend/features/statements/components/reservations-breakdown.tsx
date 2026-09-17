"use client";

import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/states";
import { Card } from "@/components/ui/card";

import type { OwnerStatementReservation } from "../data";
import { absentAmount, fmtCurrency, fmtDay } from "../lib/format";

/**
 * `null` renders as an explicit absent marker — NEVER as `0` or a computed
 * substitute (R3.5, R5.4). The marker itself is resolved through the shared
 * `absentAmount` helper from `../lib/format` so the absence glyph goes
 * through the ES/EN catalogs (steering/frontend.md: nothing visible is
 * hardcoded), and it is the same literal-dash convention already used for
 * absent per-row amounts in
 * `features/reservations/components/detail/reservation-detail-sections.tsx`.
 */
function fmtNullableCurrency(
  value: string | null,
  currency: string,
  locale: string,
): string {
  return value === null ? absentAmount(locale) : fmtCurrency(value, currency, locale);
}

export interface ReservationsBreakdownProps {
  reservations: OwnerStatementReservation[];
}

/**
 * Renders the statement detail's `reservations[]` breakdown (R3.2, R3.5,
 * task 4.2). Shows only the six contractual fields plus `currency` — no
 * subtotal, count or other aggregate is computed or displayed (R3.4): an
 * empty collection is a valid, translated empty state, not an error.
 *
 * Dates, per-row currencies and absent markers all come from
 * `../lib/format` (task 6.2). Per-row amounts use `fmtCurrency` so each
 * row carries its own `currency` — the summary's currency-less `fmtAmount`
 * would be wrong here (R3.6).
 */
export function ReservationsBreakdown({ reservations }: ReservationsBreakdownProps) {
  const { t, i18n } = useTranslation("statements");
  const locale = i18n.language;

  if (reservations.length === 0) {
    return (
      <EmptyState
        title={t("detail.reservations.empty.title")}
        description={t("detail.reservations.empty.description")}
      />
    );
  }

  return (
    <ul
      aria-label={t("detail.reservations.title")}
      className="flex min-w-0 flex-col gap-3"
      data-testid="reservations-breakdown"
    >
      {reservations.map((reservation) => {
        const headingId = `reservation-${reservation.id}`;
        return (
          <li key={reservation.id} aria-labelledby={headingId} className="min-w-0 list-none">
            <Card className="flex min-w-0 flex-col gap-3 p-4">
              <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
                <h3
                  id={headingId}
                  className="min-w-0 flex-1 break-words text-body-lg font-semibold text-foreground"
                >
                  <span className="sr-only">{t("detail.reservations.fields.checkIn")}: </span>
                  {fmtDay(reservation.checkInDate, locale)}
                </h3>
                <span className="min-w-0 break-all font-mono text-body-base text-muted-foreground">
                  <span className="sr-only">{t("detail.reservations.fields.id")}: </span>
                  {reservation.id}
                </span>
              </div>
              <dl className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.reservations.fields.nights")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {reservation.nights.toLocaleString(locale)}
                  </dd>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.reservations.fields.currency")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {reservation.currency}
                  </dd>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.reservations.fields.gross")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {fmtNullableCurrency(reservation.grossAmount, reservation.currency, locale)}
                  </dd>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.reservations.fields.ota")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {fmtNullableCurrency(reservation.otaCommission, reservation.currency, locale)}
                  </dd>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.reservations.fields.net")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {fmtNullableCurrency(reservation.netAmount, reservation.currency, locale)}
                  </dd>
                </div>
              </dl>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}
