import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import {
  StatementsFilters,
  type StatementPropertyOption,
  type StatementsFiltersProps,
} from "./statements-filters";

const PROPERTIES: StatementPropertyOption[] = [
  { id: "p-1", name: "Ático Sol" },
  { id: "p-2", name: "Loft Latina" },
];

function renderFilters(overrides: Partial<StatementsFiltersProps> = {}) {
  const handlers = {
    onPropertyIdChange: vi.fn(),
    onPeriodStartFromChange: vi.fn(),
    onPeriodStartToChange: vi.fn(),
    onStatusChange: vi.fn(),
  };
  const result = render(
    <I18nProvider locale="es">
      <StatementsFilters properties={PROPERTIES} {...handlers} {...overrides} />
    </I18nProvider>,
  );
  return { ...result, ...handlers };
}

describe("StatementsFilters — property options come from the full directory (R2.2, D2)", () => {
  it("offers every property of the directory, not a page of statements", () => {
    renderFilters();
    const select = screen.getByLabelText("Vivienda");
    expect(select).toHaveTextContent("Ático Sol");
    expect(select).toHaveTextContent("Loft Latina");
    expect(select).toHaveTextContent("Todas las viviendas");
  });

  it("emits only the selected property UUID, nothing else", () => {
    const { onPropertyIdChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Vivienda"), {
      target: { value: "p-2" },
    });
    expect(onPropertyIdChange).toHaveBeenCalledWith("p-2");
    expect(onPropertyIdChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ id: expect.anything() }),
    );
  });

  it("clears the property filter back to undefined", () => {
    const { onPropertyIdChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "" } });
    expect(onPropertyIdChange).toHaveBeenCalledWith(undefined);
  });

  it("renders with an empty directory without breaking", () => {
    renderFilters({ properties: [] });
    expect(screen.getByLabelText("Vivienda")).toHaveTextContent("Todas las viviendas");
  });
});

describe("StatementsFilters — period range (R2.3)", () => {
  it("writes both ends of the period range with native date inputs", () => {
    const { onPeriodStartFromChange, onPeriodStartToChange } = renderFilters();
    expect(screen.getByLabelText("Período desde")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("Período hasta")).toHaveAttribute("type", "date");
    fireEvent.change(screen.getByLabelText("Período desde"), {
      target: { value: "2026-01-01" },
    });
    fireEvent.change(screen.getByLabelText("Período hasta"), {
      target: { value: "2026-01-31" },
    });
    expect(onPeriodStartFromChange).toHaveBeenCalledWith("2026-01-01");
    expect(onPeriodStartToChange).toHaveBeenCalledWith("2026-01-31");
  });
});

describe("StatementsFilters — status (R2.3)", () => {
  it("lists the three contractual statuses", () => {
    renderFilters();
    const select = screen.getByLabelText("Estado");
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toEqual(["Todos los estados", "Borrador", "Lista", "Enviada"]);
  });

  it("writes the chosen status", () => {
    const { onStatusChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "READY" } });
    expect(onStatusChange).toHaveBeenCalledWith("READY");
  });

  it("clears the status filter back to undefined", () => {
    const { onStatusChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "" } });
    expect(onStatusChange).toHaveBeenCalledWith(undefined);
  });
});

describe("StatementsFilters — no tenant_id ever travels from the UI (security.md rule 1)", () => {
  it("never calls a handler with a tenant_id-shaped payload", () => {
    const handlers = renderFilters();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "SENT" } });
    for (const fn of [
      handlers.onPropertyIdChange,
      handlers.onStatusChange,
      handlers.onPeriodStartFromChange,
      handlers.onPeriodStartToChange,
    ]) {
      for (const call of fn.mock.calls) {
        for (const arg of call) {
          expect(typeof arg === "object" && arg !== null && "tenant_id" in arg).toBe(
            false,
          );
        }
      }
    }
  });
});

describe("StatementsFilters — accessibility", () => {
  it("labels every control programmatically", async () => {
    const { container } = renderFilters();
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("uses touch-sized controls", () => {
    renderFilters();
    for (const label of ["Vivienda", "Período desde", "Período hasta", "Estado"]) {
      expect(screen.getByLabelText(label)).toHaveClass("tap-target");
    }
  });
});
