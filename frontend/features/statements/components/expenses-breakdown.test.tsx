import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { getA11yViolations, render, screen } from "@/test/render";

import type { OwnerStatementExpense } from "../data";
import { ExpensesBreakdown } from "./expenses-breakdown";

const EXPENSE: OwnerStatementExpense = {
  id: "exp-1",
  category: "CLEANING",
  description: "Limpieza de salida",
  amount: "45.00",
  currency: "EUR",
  date: "2026-01-10",
};

function renderBreakdown(expenses: OwnerStatementExpense[]) {
  return render(
    <I18nProvider locale="es">
      <ExpensesBreakdown expenses={expenses} />
    </I18nProvider>,
  );
}

describe("ExpensesBreakdown — only the contractual fields (R3.3, task 4.3)", () => {
  it("shows id, category, description, amount, currency and date", () => {
    renderBreakdown([EXPENSE]);
    expect(screen.getByText("exp-1")).toBeInTheDocument();
    expect(screen.getByText("Limpieza")).toBeInTheDocument(); // translated category
    expect(screen.getByText("Limpieza de salida")).toBeInTheDocument();
    expect(screen.getByText("EUR")).toBeInTheDocument();
    expect(screen.getByText(/45,00/)).toBeInTheDocument();
    expect(screen.getByText(/ene 2026/i)).toBeInTheDocument();
  });

  it("translates every expense category", () => {
    const categories: OwnerStatementExpense["category"][] = [
      "CLEANING",
      "LAUNDRY",
      "AMENITIES",
      "MAINTENANCE",
      "SPECIALIST",
      "PLATFORM_FEE",
      "OTHER",
    ];
    renderBreakdown(categories.map((category, index) => ({ ...EXPENSE, id: `exp-${index}`, category })));
    for (const category of categories) {
      expect(screen.queryByText(`detail.expenses.category.${category}`)).not.toBeInTheDocument();
    }
  });

  it("respects each row's own currency instead of a global one", () => {
    renderBreakdown([
      { ...EXPENSE, id: "exp-1", currency: "EUR" },
      { ...EXPENSE, id: "exp-2", currency: "USD" },
    ]);
    expect(screen.getByText("EUR")).toBeInTheDocument();
    expect(screen.getByText("USD")).toBeInTheDocument();
  });

  it("never invents a subtotal or aggregate across rows", () => {
    renderBreakdown([
      { ...EXPENSE, id: "exp-1", amount: "10.00" },
      { ...EXPENSE, id: "exp-2", amount: "20.00" },
    ]);
    expect(screen.queryByText(/30[,.]00/)).not.toBeInTheDocument();
  });
});

describe("ExpensesBreakdown — empty state (R3.4)", () => {
  it("shows a translated empty state when there are no expenses", () => {
    renderBreakdown([]);
    expect(screen.getByText("Sin gastos")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("ExpensesBreakdown — accessibility", () => {
  it("has no accessibility violations with rows", async () => {
    const { container } = renderBreakdown([EXPENSE]);
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("has no accessibility violations when empty", async () => {
    const { container } = renderBreakdown([]);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
