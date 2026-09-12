import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PropertySummary } from "../data";
import { ReviewFilters, type ReviewFiltersProps } from "./review-filters";

const PROPERTIES: PropertySummary[] = [
  { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
  { id: "p-2", name: "Loft Latina", internalCode: "MAD-02" },
];

function renderFilters(overrides: Partial<ReviewFiltersProps> = {}) {
  const handlers = {
    onPropertyIdChange: vi.fn(),
    onChannelChange: vi.fn(),
    onSentimentChange: vi.fn(),
    onRatingMinChange: vi.fn(),
    onRatingMaxChange: vi.fn(),
    onDateFromChange: vi.fn(),
    onDateToChange: vi.fn(),
  };
  const result = render(
    <I18nProvider locale="es">
      <ReviewFilters
        catalog={PROPERTIES}
        {...handlers}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { ...result, ...handlers };
}

describe("ReviewFilters — the common six filters (R2.1, R5.1)", () => {
  it("offers every property of the catalog", () => {
    renderFilters();
    const select = screen.getByLabelText("Vivienda");
    expect(select).toHaveTextContent("Ático Sol");
    expect(select).toHaveTextContent("Loft Latina");
    expect(select).toHaveTextContent("Todas las viviendas");
  });

  it("writes the chosen property", () => {
    const { onPropertyIdChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Vivienda"), {
      target: { value: "p-2" },
    });
    expect(onPropertyIdChange).toHaveBeenCalledWith("p-2");
  });

  it("clears the property filter back to undefined", () => {
    const { onPropertyIdChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "" } });
    expect(onPropertyIdChange).toHaveBeenCalledWith(undefined);
  });

  it("lists the five channels", () => {
    renderFilters();
    const select = screen.getByLabelText("Canal");
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toEqual([
      "Todos los canales",
      "Airbnb",
      "Booking",
      "Google",
      "Manual",
      "Otro",
    ]);
  });

  it("writes the chosen channel", () => {
    const { onChannelChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Canal"), {
      target: { value: "GOOGLE" },
    });
    expect(onChannelChange).toHaveBeenCalledWith("GOOGLE");
  });

  it("lists the three sentiments", () => {
    renderFilters();
    const select = screen.getByLabelText("Sentimiento");
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toEqual([
      "Todos los sentimientos",
      "Positivo",
      "Neutro",
      "Negativo",
    ]);
  });

  it("writes the chosen sentiment", () => {
    const { onSentimentChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Sentimiento"), {
      target: { value: "NEGATIVE" },
    });
    expect(onSentimentChange).toHaveBeenCalledWith("NEGATIVE");
  });

  it("writes both ends of the rating range", () => {
    const { onRatingMinChange, onRatingMaxChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Mínimo"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Máximo"), { target: { value: "4.5" } });
    expect(onRatingMinChange).toHaveBeenCalledWith("2");
    expect(onRatingMaxChange).toHaveBeenCalledWith("4.5");
  });

  it("writes both ends of the date range with native date inputs", () => {
    const { onDateFromChange, onDateToChange } = renderFilters();
    expect(screen.getByLabelText("Desde")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("Hasta")).toHaveAttribute("type", "date");
    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByLabelText("Hasta"), {
      target: { value: "2026-09-30" },
    });
    expect(onDateFromChange).toHaveBeenCalledWith("2026-09-01");
    expect(onDateToChange).toHaveBeenCalledWith("2026-09-30");
  });
});

describe("ReviewFilters — status is opt-in (R2.1 Borradores has none, R5.1 Reseñas does)", () => {
  it("does not render a status selector when onStatusChange is not passed", () => {
    renderFilters();
    expect(screen.queryByLabelText("Estado")).not.toBeInTheDocument();
  });

  it("renders the five statuses when the caller passes onStatusChange", () => {
    const onStatusChange = vi.fn();
    renderFilters({ onStatusChange });
    const select = screen.getByLabelText("Estado");
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toEqual([
      "Todos los estados",
      "Nueva",
      "Borrador",
      "Aprobada",
      "Publicada manualmente",
      "Ignorada",
    ]);
    fireEvent.change(select, { target: { value: "APPROVED" } });
    expect(onStatusChange).toHaveBeenCalledWith("APPROVED");
  });
});

describe("ReviewFilters — accessibility", () => {
  it("labels every control", async () => {
    const { container } = renderFilters({ onStatusChange: vi.fn() });
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("renders with an empty catalog without breaking", () => {
    renderFilters({ catalog: [] });
    expect(screen.getByLabelText("Vivienda")).toHaveTextContent(
      "Todas las viviendas",
    );
  });
});
