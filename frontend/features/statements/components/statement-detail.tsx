"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { OwnerStatementDetail } from "../data";
import { ExpensesBreakdown } from "./expenses-breakdown";
import { ReservationsBreakdown } from "./reservations-breakdown";
import { StatementSummary } from "./statement-summary";

export interface StatementDetailProps {
  statement: OwnerStatementDetail;
  /**
   * Seam for section 5.3's `StatementDownloads` (CSV/PDF export controls).
   * Intentionally optional and untyped beyond `ReactNode`: this component
   * does not know about the download hook/lib yet (out of scope for section
   * 4) — it only reserves where the controls mount once built, so 5.3 does
   * not need to reshape this component's props.
   */
  downloads?: ReactNode;
}

/**
 * Assembles one statement's full financial detail (R3.1, task 4.1-4.3): the
 * flat summary plus the reservations/expenses breakdowns. Purely
 * presentational — it receives an already-loaded `OwnerStatementDetail` and
 * renders it; the loading/error/not-found coordination is
 * `StatementDetailState`'s job (task 4.4), not this component's.
 *
 * The summary stays visible regardless of whether either breakdown is empty
 * (R5.3, R3.4): `ReservationsBreakdown`/`ExpensesBreakdown` each own their
 * own translated empty state and are rendered unconditionally alongside the
 * summary, never gating it.
 */
export function StatementDetail({ statement, downloads }: StatementDetailProps) {
  const { t } = useTranslation("statements");
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="statement-detail">
      <StatementSummary statement={statement} />
      {downloads}
      <section aria-labelledby="statement-detail-reservations-heading" className="flex min-w-0 flex-col gap-3">
        <h2
          id="statement-detail-reservations-heading"
          className="text-headline-md font-semibold text-foreground"
        >
          {t("detail.reservations.title")}
        </h2>
        <ReservationsBreakdown reservations={statement.reservations} />
      </section>
      <section aria-labelledby="statement-detail-expenses-heading" className="flex min-w-0 flex-col gap-3">
        <h2
          id="statement-detail-expenses-heading"
          className="text-headline-md font-semibold text-foreground"
        >
          {t("detail.expenses.title")}
        </h2>
        <ExpensesBreakdown expenses={statement.expenses} />
      </section>
    </div>
  );
}
