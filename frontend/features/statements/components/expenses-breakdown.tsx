"use client";

import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/states";
import { Card } from "@/components/ui/card";

import type { OwnerStatementExpense } from "../data";
import { fmtCurrency, fmtDay } from "../lib/format";

export interface ExpensesBreakdownProps {
  expenses: OwnerStatementExpense[];
}

/**
 * Renders the statement detail's `expenses[]` breakdown (R3.3, task 4.3).
 * Shows only the six contractual fields — no subtotal or other aggregate is
 * computed or displayed (R3.4): an empty collection is a valid, translated
 * empty state, not an error.
 *
 * Dates and per-row currencies come from `../lib/format` (task 6.2).
 * Per-row amounts use `fmtCurrency` so each row carries its own `currency`
 * — the summary's currency-less `fmtAmount` would be wrong here (R3.6).
 * Unlike the reservation amounts, `OwnerStatementExpense.amount` is never
 * null, so there is no absent-value branch here (R3.3 lists no nullable
 * field).
 */
export function ExpensesBreakdown({ expenses }: ExpensesBreakdownProps) {
  const { t, i18n } = useTranslation("statements");
  const locale = i18n.language;

  if (expenses.length === 0) {
    return (
      <EmptyState
        title={t("detail.expenses.empty.title")}
        description={t("detail.expenses.empty.description")}
      />
    );
  }

  return (
    <ul
      aria-label={t("detail.expenses.title")}
      className="flex min-w-0 flex-col gap-3"
      data-testid="expenses-breakdown"
    >
      {expenses.map((expense) => {
        const headingId = `expense-${expense.id}`;
        return (
          <li key={expense.id} aria-labelledby={headingId} className="min-w-0 list-none">
            <Card className="flex min-w-0 flex-col gap-3 p-4">
              <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
                <h3
                  id={headingId}
                  className="min-w-0 flex-1 break-words text-body-lg font-semibold text-foreground"
                >
                  {expense.description}
                </h3>
                <span className="min-w-0 break-all font-mono text-body-base text-muted-foreground">
                  <span className="sr-only">{t("detail.expenses.fields.id")}: </span>
                  {expense.id}
                </span>
              </div>
              <dl className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.expenses.fields.category")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {t(`detail.expenses.category.${expense.category}`)}
                  </dd>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.expenses.fields.date")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {fmtDay(expense.date, locale)}
                  </dd>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.expenses.fields.currency")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {expense.currency}
                  </dd>
                </div>
                <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
                  <dt className="text-muted-foreground">{t("detail.expenses.fields.amount")}</dt>
                  <dd className="min-w-0 break-words text-body-medium text-foreground">
                    {fmtCurrency(expense.amount, expense.currency, locale)}
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
