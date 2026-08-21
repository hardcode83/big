import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import { useInboxFiltersStore } from "../state/use-inbox-filters-store";
import { InboxFilters } from "./inbox-filters";

const usePropertyLabels = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-conversations", () => ({ usePropertyLabels }));

function renderFilters() {
  render(
    <I18nProvider locale="es">
      <InboxFilters />
    </I18nProvider>,
  );
}

beforeEach(() => {
  usePropertyLabels.mockReset();
  usePropertyLabels.mockReturnValue({
    data: {
      items: [{ id: "property-1", internalCode: "REDES11", name: "Redes 11" }],
      page: 1,
      perPage: 100,
      total: 1,
      totalPages: 1,
    },
  });
  useInboxFiltersStore.getState().reset();
});

describe("InboxFilters — the options come from the contract (task 5.4, R2.1, R2.2)", () => {
  it("offers every value of both closed enums, plus an unselected option", () => {
    renderFilters();

    const status = screen.getByLabelText("Estado") as HTMLSelectElement;
    expect(
      Array.from(status.options).map((option) => option.value),
    ).toEqual(["", "OPEN", "RESOLVED", "ESCALATED", "CLOSED"]);

    const escalation = screen.getByLabelText("Escalación") as HTMLSelectElement;
    expect(
      Array.from(escalation.options).map((option) => option.value),
    ).toEqual(["", "NONE", "PENDING_HUMAN", "HUMAN_HANDLING", "RESOLVED"]);
  });

  it("fills the property filter from the cached label query", () => {
    renderFilters();
    const property = screen.getByLabelText("Propiedad") as HTMLSelectElement;
    expect(Array.from(property.options).map((option) => option.value)).toEqual([
      "",
      "property-1",
    ]);
    expect(usePropertyLabels).toHaveBeenCalled();
  });

  it("keeps unselected filters out of the store, so they are not sent", () => {
    renderFilters();

    fireEvent.change(screen.getByLabelText("Estado"), {
      target: { value: "ESCALATED" },
    });
    expect(useInboxFiltersStore.getState()).toMatchObject({
      status: "ESCALATED",
      escalationStatus: undefined,
      propertyId: undefined,
    });

    fireEvent.change(screen.getByLabelText("Estado"), {
      target: { value: "" },
    });
    expect(useInboxFiltersStore.getState().status).toBeUndefined();
  });

  it("resets the page when a filter changes", () => {
    useInboxFiltersStore.getState().setPage(5);
    renderFilters();

    fireEvent.change(screen.getByLabelText("Propiedad"), {
      target: { value: "property-1" },
    });
    expect(useInboxFiltersStore.getState().page).toBe(1);
  });
});

describe("InboxFilters — the CLOSED note, and only there (task 5.4, R2.3)", () => {
  const NOTE =
    "Hoy ninguna acción produce el estado «Cerrada», así que este filtro no devuelve resultados.";

  it("shows the note when CLOSED is selected and links it to the select", () => {
    renderFilters();
    fireEvent.change(screen.getByLabelText("Estado"), {
      target: { value: "CLOSED" },
    });

    const note = screen.getByText(NOTE);
    expect(note).toBeInTheDocument();
    expect(screen.getByLabelText("Estado")).toHaveAttribute(
      "aria-describedby",
      note.id,
    );
  });

  it("does not show it for any other status", () => {
    renderFilters();
    for (const value of ["", "OPEN", "RESOLVED", "ESCALATED"]) {
      fireEvent.change(screen.getByLabelText("Estado"), { target: { value } });
      expect(screen.queryByText(NOTE)).toBeNull();
    }
  });

  it("never shows it for HUMAN_HANDLING, which is reachable and does return rows", () => {
    renderFilters();
    fireEvent.change(screen.getByLabelText("Escalación"), {
      target: { value: "HUMAN_HANDLING" },
    });

    expect(screen.queryByText(NOTE)).toBeNull();
    expect(screen.getByLabelText("Escalación")).not.toHaveAttribute(
      "aria-describedby",
    );
  });
});
