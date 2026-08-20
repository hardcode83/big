import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esIncidents from "@/locales/es/incidents.json";

import { IncidentsFilters } from "./incidents-filters";

function renderFilters(
  value: Parameters<typeof IncidentsFilters>[0]["value"] = {},
  onChange: Parameters<typeof IncidentsFilters>[0]["onChange"] = () => undefined,
) {
  return render(
    <I18nProvider locale="es">
      <IncidentsFilters value={value} onChange={onChange} />
    </I18nProvider>,
  );
}

describe("IncidentsFilters", () => {
  it("renders the status and severity selects and the clear button", () => {
    renderFilters();
    expect(screen.getByLabelText(esIncidents.fields.status)).toBeInTheDocument();
    expect(
      screen.getByLabelText(esIncidents.fields.severity),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.clearFilters }),
    ).toBeInTheDocument();
  });

  it("calls onChange with the new status when status changes", () => {
    let captured: unknown = null;
    renderFilters({}, (next) => {
      captured = next;
    });
    fireEvent.change(screen.getByLabelText(esIncidents.fields.status), {
      target: { value: "OPEN" },
    });
    expect(captured).toEqual({ status: "OPEN", page: 1 });
  });

  it("calls onChange with the new severity when severity changes", () => {
    let captured: unknown = null;
    renderFilters({}, (next) => {
      captured = next;
    });
    fireEvent.change(screen.getByLabelText(esIncidents.fields.severity), {
      target: { value: "HIGH" },
    });
    expect(captured).toEqual({ severity: "HIGH", page: 1 });
  });

  it("calls onChange({}) when the clear-filters button is pressed", () => {
    let captured: unknown = "untouched";
    renderFilters({ status: "OPEN" }, (next) => {
      captured = next;
    });
    fireEvent.click(
      screen.getByRole("button", { name: esIncidents.fields.clearFilters }),
    );
    expect(captured).toEqual({});
  });

  it("does NOT include propertyId / property_id in the onChange payload", () => {
    let captured: unknown = null;
    renderFilters({}, (next) => {
      captured = next;
    });
    fireEvent.change(screen.getByLabelText(esIncidents.fields.status), {
      target: { value: "OPEN" },
    });
    fireEvent.change(screen.getByLabelText(esIncidents.fields.severity), {
      target: { value: "HIGH" },
    });
    expect(captured).not.toHaveProperty("propertyId");
    expect(captured).not.toHaveProperty("property_id");
  });
});