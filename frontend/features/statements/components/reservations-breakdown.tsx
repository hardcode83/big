"use client";

import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/states";
import { Card } from "@/components/ui/card";

import type { OwnerStatementReservation } from "../data";

/**
 * A `YYYY-MM-DD` day as the locale's medium date, UTC-anchored. Deliberate,
 * temporary duplicate of `statement-row.tsx`/`statement-summary.tsx`'s own
 * copy — this section does not build the shared module (that is task 6.2).
 *
 * TODO(section 6.2): replace with the shared `features/statements/lib/format.ts`.
 */
function fmtDay(isoDay: string, locale: string): string {
  const date = new Date(isoDay);
  if (Number.isNaN(date.getTime())) {
    return isoDay;
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

/**
 * A row's own decimal amount, formatted with ITS OWN `currency` (R3.6): each
 * reservation may carry a different currency, so the summary's currency-less
 * `fmtAmount` would be wrong here. `Intl.NumberFormat`'s `style: "currency"`
 * both localizes the decimals and paints the right symbol/code for that row
 * — no cross-row aggregation and no conversion happen anywhere in this file.
 * A currency code `Intl` cannot resolve (never expected from this API) falls
 * back to a plain decimal + the raw code rather than throwing.
 *
 * TODO(section 6.2): replace with the shared `features/statements/lib/format.ts`.
 */
function fmtCurrency(value: string, currency: string, locale: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return value;
  }
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency }).format(num);
  } catch {
    return `${num.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
  }
}

/**
 * `null` renders as an explicit absent marker — NEVER as `0` or a computed
 * substitute (R3.5). Same literal-dash convention already used for absent
 * per-row amounts in `features/reservations/components/detail/reservation-detail-sections.tsx`.
 */
function fmtNullableCurrency(
  value: string | null,
  currency: string,
  locale: string,
): string {
  return value === null ? "—" : fmtCurrency(value, currency, locale);
}

export interface ReservationsBreakdownProps {
  reservations: OwnerStatementReservation[];
}

/**
 * Renders the statement detail's `reservations[]` breakdown (R3.2, R3.5,
 * task 4.2). Shows only the six contractual fields plus `currency` — no
 * subtotal, count or other aggregate is computed or displayed (R3.4): an
 * empty collection is a valid, translated empty state, not an error.
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
